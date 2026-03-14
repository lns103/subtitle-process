import os
import re

def parse_srt_time(time_str):
    parts = re.split(r'[:,]', time_str)
    if len(parts) == 4:
        h, m, s, ms = map(int, parts)
        return h * 3600 + m * 60 + s + ms / 1000.0
    return 0.0

def format_srt_time(seconds):
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms >= 1000:
        ms -= 1000
        s += 1
    if s >= 60:
        s -= 60
        m += 1
    if m >= 60:
        m -= 60
        h += 1
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def parse_ass_time(time_str):
    parts = re.split(r'[:.]', time_str)
    if len(parts) == 4:
        h, m, s, cs = map(int, parts)
        return h * 3600 + m * 60 + s + cs / 100.0
    return 0.0

def format_ass_time(seconds):
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs -= 100
        s += 1
    if s >= 60:
        s -= 60
        m += 1
    if m >= 60:
        m -= 60
        h += 1
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def parse_fps(fps_val):
    fps_str = str(fps_val).strip()
    
    precise_map = {
        "23.976": "24000/1001",
        "23.98": "24000/1001",
        "29.97": "30000/1001",
        "59.94": "60000/1001"
    }
    if fps_str in precise_map:
        fps_str = precise_map[fps_str]

    # Handle fractions like "24000/1001" or "30000/1001"
    if '/' in fps_str:
        parts = fps_str.split('/')
        if len(parts) == 2:
            try:
                num = int(parts[0])
                den = int(parts[1])
                if den != 0:
                    return num / den
            except ValueError:
                pass
    
    # Try parsing as standard float
    try:
        return float(fps_str)
    except ValueError:
        raise ValueError(f"无法解析帧率值: {fps_val}")

def process_file(filepath, src_fps_val, dst_fps_val):
    try:
        src_fps = parse_fps(src_fps_val)
        dst_fps = parse_fps(dst_fps_val)
    except Exception as e:
        return False, str(e)
        
    if src_fps == dst_fps:
        return True, f"源帧率和目标帧率相同 ({src_fps})，跳过: {os.path.basename(filepath)}"
        
    ext = os.path.splitext(filepath)[1].lower()
    if ext not in ['.srt', '.ass']:
        return False, f"不支持的格式 {ext}: {os.path.basename(filepath)}"
        
    ratio = src_fps / dst_fps
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        try:
            with open(filepath, 'r', encoding='gbk') as f:
                lines = f.readlines()
        except Exception as e:
            return False, f"读取文件失败 {os.path.basename(filepath)}: {e}"
            
    out_lines = []
    
    if ext == '.srt':
        srt_time_pattern = re.compile(r'^(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})')
        for line in lines:
            match = srt_time_pattern.search(line)
            if match:
                start_str, end_str = match.groups()
                start_sec = parse_srt_time(start_str) * ratio
                end_sec = parse_srt_time(end_str) * ratio
                new_start = format_srt_time(start_sec)
                new_end = format_srt_time(end_sec)
                # 替换原来的时间戳部分
                new_line = line[:match.start()] + f"{new_start} --> {new_end}" + line[match.end():]
                out_lines.append(new_line)
            else:
                out_lines.append(line)
    elif ext == '.ass':
        # ASS Format Example: Dialogue: 0,0:00:20.00,0:00:22.00,Default,,0,0,0,,Text
        ass_time_pattern = re.compile(r'^(Dialogue|Comment):\s*([^,]*),(\d{1,2}:\d{2}:\d{2}\.\d{2}),(\d{1,2}:\d{2}:\d{2}\.\d{2}),(.*)$', re.DOTALL)
        for line in lines:
            match = ass_time_pattern.match(line)
            if match:
                evt_type, layer, start_str, end_str, rest = match.groups()
                start_sec = parse_ass_time(start_str) * ratio
                end_sec = parse_ass_time(end_str) * ratio
                new_start = format_ass_time(start_sec)
                new_end = format_ass_time(end_sec)
                out_lines.append(f"{evt_type}: {layer},{new_start},{new_end},{rest}")
            else:
                out_lines.append(line)
                
    # 覆盖原文件前备份
    bak_path = filepath + ".bak"
    try:
        if not os.path.exists(bak_path):
            os.rename(filepath, bak_path)
        else:
            # 如果已有bak，先删除原文件
            os.remove(filepath)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.writelines(out_lines)
    except Exception as e:
        return False, f"保存文件失败 {os.path.basename(filepath)}: {e}"
        
    return True, f"成功转换帧率 ({src_fps_val} -> {dst_fps_val}): {os.path.basename(filepath)}"
