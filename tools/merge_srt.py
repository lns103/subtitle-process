import os
import re
import sys
from datetime import date

try:
    from tools.chs_srt_format import format_zh_text
except ImportError:
    from chs_srt_format import format_zh_text

def convert_time(srt_timestamp):
    """
    将 srt 格式时间 "00:00:02,326" 转换为 ASS 格式时间 "0:00:02.32"
    """
    # 使用正则解析时间
    m = re.match(r'(\d+):(\d+):(\d+),(\d+)', srt_timestamp)
    if not m:
        raise ValueError(f"时间格式不正确: {srt_timestamp}")
    hour, minute, second, ms = m.groups()
    # 将小时转换为不带前导0的整数，分钟和秒保持两位
    hour = str(int(hour))
    minute = minute.zfill(2)
    second = second.zfill(2)
    # 毫秒转换为两位，直接取前两位（相当于截断，不是四舍五入）
    ms = ms[:2]
    return f"{hour}:{minute}:{second}.{ms}"

def parse_srt(srt_path):
    """
    解析 srt 文件，返回每个字幕块的 (start_time, end_time, text)
    """
    with open(srt_path, "r", encoding="utf-8-sig") as f:
        content = f.read()
    
    # 按空行分块（字幕块）
    blocks = re.split(r'\n\s*\n', content.strip())
    entries = []
    for block in blocks:
        lines = block.splitlines()
        if len(lines) >= 3:
            # 第一行为序号，第二行为时间轴，其余为字幕文本
            time_line = lines[1]
            # 解析时间轴格式 "00:00:02,326 --> 00:00:03,802"
            if "-->" not in time_line:
                continue
            start_str, end_str = [s.strip() for s in time_line.split("-->")]
            start_ass = convert_time(start_str)
            end_ass = convert_time(end_str)
            # 多行字幕合并为一行，用 \N 分隔或用空格合并
            text = " ".join(lines[2:]).strip()
            entries.append((start_ass, end_ass, text))
    return entries

def merge_srt(eng_entries, zh_entries, **kwargs):
    """
    合并英文和中文字幕条目。
    首先尝试精确匹配，如果中文中缺失了任何一个英文的时间戳，则降级使用模糊匹配规则。
    """
    l2_style_name = kwargs.get("lang2_style_name", "Original")

    def get_ms(t_str):
        h, m, s_ms = t_str.split(':')
        s, ms = s_ms.split('.')
        return int(h) * 3600000 + int(m) * 60000 + int(s) * 1000 + int(ms) * 10

    # 1. 检查是否可以精确匹配（所有英文时间戳在中文里都能找到）
    eng_map = {(start, end): text for start, end, text in eng_entries}
    zh_map = {(start, end): text for start, end, text in zh_entries}
    warnings_list = kwargs.get("warnings_list", None)
    
    exact_match_success = True
    for eng_start, eng_end, _ in eng_entries:
        if (eng_start, eng_end) not in zh_map:
            exact_match_success = False
            break

    merged_entries = []

    if exact_match_success:
        # 精确匹配成功
        for zh_start, zh_end, zh_text in zh_entries:
            zh_text = format_zh_text(zh_text)
            if (zh_start, zh_end) in eng_map:
                eng_text = eng_map[(zh_start, zh_end)]
                merged_text = f"{zh_text}\\N{{\\r{l2_style_name}}}{eng_text}"
                merged_text = merged_text.replace("<i>", "").replace("</i>", "")
                merged_entries.append((zh_start, zh_end, merged_text))
            else:
                # 中文多出的字幕
                merged_text = f"{{\\an8}}{zh_text}"
                merged_entries.append((zh_start, zh_end, merged_text))
        
        merged_entries.sort(key=lambda x: get_ms(x[0]))
        return merged_entries

    # ==========================
    # 2. 精确匹配失败，启用模糊匹配规则
    # ==========================
    eng_nodes = []
    for i, (start, end, text) in enumerate(eng_entries):
        eng_nodes.append({
            'idx': i, 'start_ms': get_ms(start), 'end_ms': get_ms(end), 
            'start_str': start, 'end_str': end, 'text': text
        })
        
    zh_nodes = []
    for j, (start, end, text) in enumerate(zh_entries):
        zh_nodes.append({
            'idx': j, 'start_ms': get_ms(start), 'end_ms': get_ms(end),
            'start_str': start, 'end_str': end, 'text': text
        })

    # 构建匹配关系（二分图）
    eng_adj = {i: [] for i in range(len(eng_nodes))}
    zh_adj = {j: [] for j in range(len(zh_nodes))}
    
    for i, e in enumerate(eng_nodes):
        for j, z in enumerate(zh_nodes):
            # 规则1：起止时间戳在前后0.5s内
            c1 = abs(e['start_ms'] - z['start_ms']) <= 500 and abs(e['end_ms'] - z['end_ms']) <= 500
            # 规则2：翻译完全包含在原始时间戳内
            c2 = z['start_ms'] >= e['start_ms'] and z['end_ms'] <= e['end_ms']
            # 规则3：一条翻译时间戳包含多个原始（原始被包含在翻译中）
            c3 = e['start_ms'] >= z['start_ms'] and e['end_ms'] <= z['end_ms']
            # 规则4：某条字幕与另一边的某条字幕时间重叠大于50%
            overlap_start = max(e['start_ms'], z['start_ms'])
            overlap_end = min(e['end_ms'], z['end_ms'])
            overlap_dur = max(0, overlap_end - overlap_start)
            e_dur = e['end_ms'] - e['start_ms']
            z_dur = z['end_ms'] - z['start_ms']
            c4 = (e_dur > 0 and overlap_dur / e_dur > 0.5) or (z_dur > 0 and overlap_dur / z_dur > 0.5)
            
            if c1 or c2 or c3 or c4:
                eng_adj[i].append(j)
                zh_adj[j].append(i)

    # 规则5：孤立节点打捞（处理跨界字幕）。如果某条字幕在上述4条规则后依然孤立，
    # 寻找与其重叠最多的对面字幕，并只连接重叠最多的一条（防止合并块过长）。
    for i in range(len(eng_nodes)):
        if not eng_adj[i]:
            e = eng_nodes[i]
            best_j = -1
            max_overlap = 0
            for j in range(len(zh_nodes)):
                z = zh_nodes[j]
                overlap_start = max(e['start_ms'], z['start_ms'])
                overlap_end = min(e['end_ms'], z['end_ms'])
                overlap_dur = max(0, overlap_end - overlap_start)
                if overlap_dur > max_overlap:
                    max_overlap = overlap_dur
                    best_j = j
            
            e_dur = e['end_ms'] - e['start_ms']
            if best_j != -1 and (max_overlap > 0.3 * e_dur or max_overlap > 500):
                eng_adj[i].append(best_j)
                zh_adj[best_j].append(i)

    for j in range(len(zh_nodes)):
        if not zh_adj[j]:
            z = zh_nodes[j]
            best_i = -1
            max_overlap = 0
            for i in range(len(eng_nodes)):
                e = eng_nodes[i]
                overlap_start = max(e['start_ms'], z['start_ms'])
                overlap_end = min(e['end_ms'], z['end_ms'])
                overlap_dur = max(0, overlap_end - overlap_start)
                if overlap_dur > max_overlap:
                    max_overlap = overlap_dur
                    best_i = i
                    
            z_dur = z['end_ms'] - z['start_ms']
            if best_i != -1 and (max_overlap > 0.3 * z_dur or max_overlap > 500):
                eng_adj[best_i].append(j)
                zh_adj[j].append(best_i)

    # 寻找连通分量，合并匹配项
    visited_eng = set()
    visited_zh = set()
    components = []

    for i in range(len(eng_nodes)):
        if i in visited_eng:
            continue
        
        comp_eng = set()
        comp_zh = set()
        q_eng = [i]
        q_zh = []
        
        while q_eng or q_zh:
            while q_eng:
                e_idx = q_eng.pop(0)
                if e_idx in comp_eng: continue
                comp_eng.add(e_idx)
                visited_eng.add(e_idx)
                for z_idx in eng_adj[e_idx]:
                    if z_idx not in comp_zh:
                        q_zh.append(z_idx)
            while q_zh:
                z_idx = q_zh.pop(0)
                if z_idx in comp_zh: continue
                comp_zh.add(z_idx)
                visited_zh.add(z_idx)
                for e_idx in zh_adj[z_idx]:
                    if e_idx not in comp_eng:
                        q_eng.append(e_idx)
                        
        components.append((comp_eng, comp_zh))

    # 找出孤立的中文字幕
    for j in range(len(zh_nodes)):
        if j not in visited_zh:
            components.append((set(), {j}))

    # 生成最终合并结果
    for comp_eng, comp_zh in components:
        e_list = sorted(list(comp_eng))
        z_list = sorted(list(comp_zh))
        
        if len(e_list) == 0 and len(z_list) > 0:
            # 孤立无法匹配的中文行 -> 输出到屏幕顶部
            for z_idx in z_list:
                z = zh_nodes[z_idx]
                zh_text = format_zh_text(z['text'])
                merged_entries.append((z['start_str'], z['end_str'], f"{{\\an8}}{zh_text}"))
                
        elif len(z_list) == 0 and len(e_list) > 0:
            # 未匹配的原始语言 -> 正常输出并警告
            for e_idx in e_list:
                e = eng_nodes[e_idx]
                warn_msg = f"警告：未找到匹配的翻译字幕！原始字幕({e['start_str']} --> {e['end_str']})"
                print(warn_msg)
                if warnings_list is not None:
                    warnings_list.append(warn_msg)
                eng_clean = e['text'].replace("<i>", "").replace("</i>", "")
                merged_entries.append((e['start_str'], e['end_str'], f"{{\\r{l2_style_name}}}{eng_clean}"))
                
        else:
            # 成功匹配的组（可能是1对1，1对多，多对1）
            # 时间戳使用原始时间戳（起点最早，终点最晚）
            start_str = eng_nodes[e_list[0]]['start_str']
            end_str = eng_nodes[e_list[-1]]['end_str']
            
            zh_texts = [format_zh_text(zh_nodes[z_idx]['text']) for z_idx in z_list]
            zh_merged = " ".join(zh_texts)
            
            eng_texts = [eng_nodes[e_idx]['text'].replace("<i>", "").replace("</i>", "") for e_idx in e_list]
            eng_merged = " ".join(eng_texts)
            
            merged_text = f"{zh_merged}\\N{{\\r{l2_style_name}}}{eng_merged}"
            merged_entries.append((start_str, end_str, merged_text))

    # 按时间戳排序
    merged_entries.sort(key=lambda x: get_ms(x[0]))
    return merged_entries

def write_ass(merged_entries, output_path, filename, **kwargs):
    """
    写入 ASS 文件，包含头部信息和合并后的字幕，title为文件名，comment为日期信息yyyy-mm-dd
    """
    today = date.today().isoformat()
    
    author = kwargs.get("author", "lns103")
    comment = kwargs.get("comment", f"{today} made by my SRT merge script")
    
    playresx = kwargs.get("playresx", 1920)
    playresy = kwargs.get("playresy", 1080)
    
    l1_style_name = kwargs.get("lang1_style_name", "Chinese")
    l1_style_def = kwargs.get("lang1_style_def", "黑体, 60, &H00EEEEEE, &HF0000000, &H00000000, &H32000000, 0, 0, 0, 0, 100, 100, 0, 0, 1, 1.5, 0, 2, 18, 18, 18, 1")
    
    l2_style_name = kwargs.get("lang2_style_name", "Original")
    l2_style_def = kwargs.get("lang2_style_def", "Arial, 40, &H00EEEEEE, &HF0000000, &H00000000, &H32000000, 0, 0, 0, 0, 100, 100, 0, 0, 1, 1.5, 0, 2, 18, 18, 18, 1")

    header = (
        "[Script Info]\n"
        f"Title: {filename}\n"
        f"Author: {author}\n"
        f"Comment: {comment}\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {playresx}\n"
        f"PlayResY: {playresy}\n"
        "Timer: 100.0000\n"
        "WrapStyle: 0\n"
        "YCbCr Matrix: TV.709\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: {l1_style_name}, {l1_style_def}\n"
        f"Style: {l2_style_name}, {l2_style_def}\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(header)
        for start, end, text in merged_entries:
            # text itself contains the \N{\rOriginal} tag, so we just need to ensure the first word matches l2_style_name if it was modified
            # if we changed lang2_style_name, we also need to modify the \r tag inside the text.
            # but wait, merge_srt hardcodes {\rOriginal}
            line = f"Dialogue: 0,{start},{end},{l1_style_name},,0,0,0,,{text}\n"
            f.write(line)

def merge_and_save(eng_path, zh_path, output_path, filename, **kwargs):
    """
    合并单个中英文字幕对并保存为 ASS
    """
    try:
        eng_entries = parse_srt(eng_path)
        zh_entries = parse_srt(zh_path)
        
        warnings_list = []
        kwargs["warnings_list"] = warnings_list
        merged_entries = merge_srt(eng_entries, zh_entries, **kwargs)
        
        write_ass(merged_entries, output_path, filename, **kwargs)
        print(f"生成文件: {output_path}")
        
        msg = f"生成文件: {os.path.basename(output_path)}"
        if warnings_list:
            msg += "\n" + "\n".join(warnings_list)
            
        return True, msg
    except Exception as e:
        print(f"处理 {filename} 时出错: {e}")
        return False, f"处理失败 {filename}: {e}"

def process_directory(folder, **kwargs):
    """
    处理目录下的双语字幕合并
    """
    results = []
    
    translated_suffix = kwargs.get("translated_suffix", ".zh.srt").strip()
    if translated_suffix.lower().endswith(".srt"):
         translated_suffix = translated_suffix[:-4]
    if not translated_suffix.startswith("."):
         translated_suffix = "." + translated_suffix
    
    full_translated_suffix = translated_suffix + ".srt"
         
    # 查找文件夹下所有 *.srt 文件
    files = [f for f in os.listdir(folder) if f.endswith(".srt")]
    # 筛选英文文件（假设不包含 translated_suffix）
    eng_files = [f for f in files if not f.endswith(full_translated_suffix) and not f.endswith(".zh-CN.srt") and not f.endswith(".zh.srt")]
    
    # 确保输出目录存在
    output_folder = os.path.join(folder, "merge")
    os.makedirs(output_folder, exist_ok=True)
    
    for eng_file in eng_files:
        base, ext = os.path.splitext(eng_file)
        zh_file = f"{base}{full_translated_suffix}"
        eng_path = os.path.join(folder, eng_file)
        zh_path = os.path.join(folder, zh_file)
        
        if not os.path.exists(zh_path):
             # 尝试 fallback 为 .zh.srt 或 .zh-CN.srt 如果需要向后兼容，但优先使用后缀匹配
            if os.path.exists(os.path.join(folder, f"{base}.zh.srt")):
                 zh_path = os.path.join(folder, f"{base}.zh.srt")
            elif os.path.exists(os.path.join(folder, f"{base}.zh-CN.srt")):
                 zh_path = os.path.join(folder, f"{base}.zh-CN.srt")
            else:
                 print(f"对应的中文文件不存在: {zh_path}")
                 results.append(f"跳过 {eng_file}: 找不到对应的中文文件")
                 continue
        
        # 输出文件名格式：xxx.zh&en.ass
        output_suffix = kwargs.get("output_suffix", ".zh&en.ass")
        output_filename = f"{base}{output_suffix}"
        output_path = os.path.join(output_folder, output_filename)
        
        success, msg = merge_and_save(eng_path, zh_path, output_path, base, **kwargs)
        results.append(msg)
        
    return results

def process_files(file_list, **kwargs):
    """
    处理给定的文件列表中的双语字幕合并
    :param file_list: 文件路径列表
    """
    results = []
    
    translated_suffix = kwargs.get("translated_suffix", ".zh.srt").strip()
    if translated_suffix.lower().endswith(".srt"):
         translated_suffix = translated_suffix[:-4]
    if not translated_suffix.startswith("."):
         translated_suffix = "." + translated_suffix
         
    full_translated_suffix = translated_suffix + ".srt"
    
    # 1. 分类文件
    eng_files = []
    zh_files = [] # 存储中文文件路径，便于后续检查是否匹配
    
    # helper for checking zh
    def is_zh_file(f):
        return f.endswith(full_translated_suffix) or f.endswith(".zh.srt") or f.endswith(".zh-CN.srt")
        
    for f in file_list:
        if not f.endswith(".srt"):
            continue
            
        if is_zh_file(f):
            zh_files.append(f)
        else:
            eng_files.append(f)
    
    # 2. 建立查找字典: base_name -> full_path for .zh.srt
    zh_map = {}
    for f in zh_files:
        if f.endswith(full_translated_suffix):
            base = f[:-len(full_translated_suffix)]
        elif f.endswith(".zh.srt"):
            # key: d:/path/video.zh.srt -> d:/path/video
            base = f[:-7] 
        elif f.endswith(".zh-CN.srt"):
             base = f[:-10]
        else:
            continue
        zh_map[os.path.normpath(base).lower()] = f

    matched_count = 0
    unmatched_count = 0
    
    # 记录已匹配的中文文件集合
    matched_zh_files = set()

    # 3. 遍历英文文件寻找匹配
    for eng_path in eng_files:
        base, _ = os.path.splitext(eng_path)
        # uniform key
        key = os.path.normpath(base).lower()
        
        if key in zh_map:
            zh_path = zh_map[key]
            matched_zh_files.add(zh_path)
            
            # 确定输出目录: 就在当前文件目录下创建一个 merge 文件夹
            folder = os.path.dirname(eng_path)
            output_folder = os.path.join(folder, "merge")
            os.makedirs(output_folder, exist_ok=True)
            
            output_suffix = kwargs.get("output_suffix", ".zh&en.ass")
            output_filename = f"{os.path.basename(base)}{output_suffix}"
            output_path = os.path.join(output_folder, output_filename)
            
            success, msg = merge_and_save(eng_path, zh_path, output_path, os.path.basename(base), **kwargs)
            results.append(msg)
            matched_count += 1
        else:
            unmatched_count += 1
            results.append(f"未找到匹配中文文件: {os.path.basename(eng_path)}")
    
    # 4. 检查未匹配的中文文件
    for zh_path in zh_files:
        if zh_path not in matched_zh_files:
            unmatched_count += 1
            results.append(f"未找到匹配英文文件: {os.path.basename(zh_path)}")
            
    if matched_count > 0 or unmatched_count > 0:
        results.append(f"处理完成: 成功合并 {matched_count} 对，未匹配 {unmatched_count} 个")
            
    return results

def classify_and_match_files(file_paths, pattern):
    """
    根据特征/路径识别进行匹配。
    :param file_paths: SRT文件路径列表
    :param pattern: 匹配特征字，例如 'zh'
    :return: (matched_pairs, unmatched_original, unmatched_translated)
      - matched_pairs: [{"original": path1, "translated": path2}]
      - unmatched_original: [{"path": path1, "reason": "no_match"|"multiple_matches"}]
      - unmatched_translated: [{"path": path1, "reason": "no_match"|"multiple_matches"}]
    """
    pattern = pattern.strip().lower()
    if not pattern:
        pattern = "zh"
        
    translated_files = []
    original_files = []
    
    # 1. Classify each file
    for path in file_paths:
        if not path.lower().endswith(".srt"):
            continue
        path = os.path.abspath(path)
        filename = os.path.basename(path).lower()
        
        name_we, ext = os.path.splitext(filename)
        is_translated = False
        
        # Check name suffix: name_we ends with .pattern, _pattern, -pattern (with optional sub-tags) or is pattern
        if re.search(rf'(?:[._-]|^){re.escape(pattern)}(?:[-_][a-zA-Z0-9]+)?$', name_we):
            is_translated = True
            
        if not is_translated:
            # Check directories: check if any directory name ends with the pattern
            norm_path = path.replace('\\', '/').lower()
            parts = norm_path.split('/')
            # Check directory components (excluding drive letter and filename)
            for p in parts[1:-1]:
                if re.search(rf'(?:[._-]|^){re.escape(pattern)}(?:[-_][a-zA-Z0-9]+)?$', p):
                    is_translated = True
                    break
                    
        if is_translated:
            translated_files.append(path)
        else:
            original_files.append(path)
            
    # 2. Setup helper to get clean filename
    def get_clean_name(filepath, is_trans):
        filename = os.path.basename(filepath)
        name, ext = os.path.splitext(filename)
        name = name.lower()
        if not is_trans:
            return name
        # Remove pattern suffix
        match = re.search(rf'[._-]{re.escape(pattern)}(?:[-_][a-zA-Z0-9]+)?$', name)
        if match:
            return name[:match.start()]
        if name == pattern:
            return ""
        return name

    # Group files by clean name
    orig_by_name = {}
    for orig in original_files:
        cname = get_clean_name(orig, is_trans=False)
        orig_by_name.setdefault(cname, []).append(orig)
        
    trans_by_name = {}
    for trans in translated_files:
        cname = get_clean_name(trans, is_trans=True)
        trans_by_name.setdefault(cname, []).append(trans)
        
    matched_pairs = []
    unmatched_original = []
    unmatched_translated = []
    
    # Helper to get clean directory path
    def get_clean_dir(filepath):
        dir_path = os.path.dirname(os.path.abspath(filepath))
        norm = dir_path.replace('\\', '/').lower()
        parts = norm.split('/')
        if parts and re.search(rf'(?:[._-]|^){re.escape(pattern)}(?:[-_][a-zA-Z0-9]+)?$', parts[-1]):
            parts = parts[:-1]
        skip_folders = {"en", "eng", "english", "original", "orig", "org", "source", "src", "en-us", "en-gb", "us", "uk"}
        cleaned_parts = []
        for p in parts:
            if p not in skip_folders:
                cleaned_parts.append(p)
        return '/'.join(cleaned_parts)

    all_clean_names = set(orig_by_name.keys()) | set(trans_by_name.keys())
    
    for cname in all_clean_names:
        origs = orig_by_name.get(cname, [])
        trans = trans_by_name.get(cname, [])
        
        if not origs:
            for t in trans:
                unmatched_translated.append({"path": t, "reason": "no_match"})
            continue
        if not trans:
            for o in origs:
                unmatched_original.append({"path": o, "reason": "no_match"})
            continue
            
        # Try to match strictly within clean directory
        orig_by_dir = {}
        for o in origs:
            orig_by_dir.setdefault(get_clean_dir(o), []).append(o)
            
        trans_by_dir = {}
        for t in trans:
            trans_by_dir.setdefault(get_clean_dir(t), []).append(t)
            
        remaining_origs = list(origs)
        remaining_trans = list(trans)
        
        all_dirs = set(orig_by_dir.keys()) | set(trans_by_dir.keys())
        
        # Keep track of local conflicts in directories
        local_conflict_origs = set()
        local_conflict_trans = set()
        
        for d in all_dirs:
            o_list = orig_by_dir.get(d, [])
            t_list = trans_by_dir.get(d, [])
            if len(o_list) == 1 and len(t_list) == 1:
                o_file = o_list[0]
                t_file = t_list[0]
                matched_pairs.append({"original": o_file, "translated": t_file})
                remaining_origs.remove(o_file)
                remaining_trans.remove(t_file)
            else:
                if len(o_list) > 1:
                    local_conflict_origs.update(o_list)
                if len(t_list) > 1:
                    local_conflict_trans.update(t_list)
                    
        # Try to match remaining files globally (fuzzy match)
        if len(remaining_origs) == 1 and len(remaining_trans) == 1:
            o_file = remaining_origs[0]
            t_file = remaining_trans[0]
            if o_file not in local_conflict_origs and t_file not in local_conflict_trans:
                matched_pairs.append({"original": o_file, "translated": t_file})
                remaining_origs.remove(o_file)
                remaining_trans.remove(t_file)
                
        # Any leftover remaining files are unmatched conflicts/errors
        for o in remaining_origs:
            reason = "multiple_matches" if len(trans) > 1 or o in local_conflict_origs else "no_match"
            unmatched_original.append({"path": o, "reason": reason})
        for t in remaining_trans:
            reason = "multiple_matches" if len(origs) > 1 or t in local_conflict_trans else "no_match"
            unmatched_translated.append({"path": t, "reason": reason})
            
    # Sort for deterministic display
    matched_pairs.sort(key=lambda x: x["original"].lower())
    unmatched_original.sort(key=lambda x: x["path"].lower())
    unmatched_translated.sort(key=lambda x: x["path"].lower())
    
    return matched_pairs, unmatched_original, unmatched_translated

def main():
    if len(sys.argv) < 2:
        print("用法: python merge_srt.py <srt文件所在文件夹>")
        sys.exit(1)
    
    folder = sys.argv[1]
    process_directory(folder)

if __name__ == "__main__":
    main()
