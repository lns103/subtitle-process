import os
import re
import sys
from datetime import date

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
    合并英文和中文字幕条目，假定它们的顺序和时间完全对应
    """
    if len(eng_entries) != len(zh_entries):
        raise ValueError("英文和中文字幕的条目数量不匹配！")
    
    l2_style_name = kwargs.get("lang2_style_name", "Original")

    merged_entries = []
    for (eng_start, eng_end, eng_text), (zh_start, zh_end, zh_text) in zip(eng_entries, zh_entries):
        # 此处可以对比时间是否一致，不一致可以抛出异常或警告
        if eng_start != zh_start or eng_end != zh_end:
            print(f"警告：时间不匹配！英文({eng_start} --> {eng_end}) vs 中文({zh_start} --> {zh_end})")
        # 去除中文里的标点符号
        zh_text = zh_text.replace("，"," ").replace("、"," ").replace("——"," ").replace("。"," ").replace("！","! ").replace("？","? ")
        zh_text = zh_text.replace("“","\"").replace("”","\"").replace("‘","\'").replace("’","\'").replace("「","\"").replace("」","\"")
        zh_text = zh_text.replace("- ","-").replace("："," ")
        zh_text = re.sub(r"\s+\"","\"",zh_text)
        zh_text = re.sub(r"\s+\'","\'",zh_text)
        # zh_text = re.sub(r"\s+」","」",zh_text)
        zh_text = re.sub(r"\s+》","》",zh_text).strip()
        # zh_text = re.sub(r"\s+{\\i0}","{\\i0}",zh_text)
        
        merged_text = f"{zh_text}\\N{{\\r{l2_style_name}}}{eng_text}"
        # # 替换 <i> 和 </i> 为 ass 正确格式
        # merged_text = merged_text.replace("<i>", "{\\i1}").replace("</i>", "{\\i0}")
        # 删除 <i> 和 </i>
        merged_text = merged_text.replace("<i>", "").replace("</i>", "")
        
        merged_entries.append((eng_start, eng_end, merged_text))
    return merged_entries

def write_ass(merged_entries, output_path, filename, **kwargs):
    """
    写入 ASS 文件，包含头部信息和合并后的字幕，title为文件名，comment为日期信息yyyy-mm-dd
    """
    today = date.today().isoformat()
    
    author = kwargs.get("author", "lns103")
    comment = kwargs.get("comment", f"{today} made by my SRT merge script")
    
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
        "PlayResX: 1920\n"
        "PlayResY: 1080\n"
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
        merged_entries = merge_srt(eng_entries, zh_entries, **kwargs)
        write_ass(merged_entries, output_path, filename, **kwargs)
        print(f"生成文件: {output_path}")
        return True, f"生成文件: {os.path.basename(output_path)}"
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

def main():
    if len(sys.argv) < 2:
        print("用法: python merge_srt.py <srt文件所在文件夹>")
        sys.exit(1)
    
    folder = sys.argv[1]
    process_directory(folder)

if __name__ == "__main__":
    main()
