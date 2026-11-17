import os
import re

# 复用 fps_converter 中的时间解析和格式化函数
try:
    from .fps_converter import parse_srt_time, format_srt_time, parse_ass_time, format_ass_time
except ImportError:
    from fps_converter import parse_srt_time, format_srt_time, parse_ass_time, format_ass_time

def process_file(filepath, offset_seconds):
    try:
        offset = float(offset_seconds)
    except ValueError:
        return False, f"无法解析时间偏移量: {offset_seconds}"
        
    if offset == 0:
        return True, f"时间偏移量为 0，跳过: {os.path.basename(filepath)}"
        
    ext = os.path.splitext(filepath)[1].lower()
    if ext not in ['.srt', '.ass']:
        return False, f"不支持的格式 {ext}: {os.path.basename(filepath)}"
    
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
                start_sec = parse_srt_time(start_str) + offset
                end_sec = parse_srt_time(end_str) + offset
                new_start = format_srt_time(start_sec)
                new_end = format_srt_time(end_sec)
                new_line = line[:match.start()] + f"{new_start} --> {new_end}" + line[match.end():]
                out_lines.append(new_line)
            else:
                out_lines.append(line)
    elif ext == '.ass':
        ass_time_pattern = re.compile(r'^(Dialogue|Comment):\s*([^,]*),(\d{1,2}:\d{2}:\d{2}\.\d{2}),(\d{1,2}:\d{2}:\d{2}\.\d{2}),(.*)$', re.DOTALL)
        for line in lines:
            match = ass_time_pattern.match(line)
            if match:
                evt_type, layer, start_str, end_str, rest = match.groups()
                start_sec = parse_ass_time(start_str) + offset
                end_sec = parse_ass_time(end_str) + offset
                new_start = format_ass_time(start_sec)
                new_end = format_ass_time(end_sec)
                out_lines.append(f"{evt_type}: {layer},{new_start},{new_end},{rest}")
            else:
                out_lines.append(line)
                
    bak_path = filepath + ".bak"
    try:
        if not os.path.exists(bak_path):
            os.rename(filepath, bak_path)
        else:
            os.remove(filepath)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.writelines(out_lines)
    except Exception as e:
        return False, f"保存文件失败 {os.path.basename(filepath)}: {e}"
        
    return True, f"成功平移时间轴 ({'+' if offset > 0 else ''}{offset} 秒): {os.path.basename(filepath)}"
