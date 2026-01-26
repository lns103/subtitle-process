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

def merge_srt(eng_entries, zh_entries):
    """
    合并英文和中文字幕条目，假定它们的顺序和时间完全对应
    """
    if len(eng_entries) != len(zh_entries):
        raise ValueError("英文和中文字幕的条目数量不匹配！")
    
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
        
        merged_text = f"{zh_text}\\N{{\\rOriginal}}{eng_text}"
        # # 替换 <i> 和 </i> 为 ass 正确格式
        # merged_text = merged_text.replace("<i>", "{\\i1}").replace("</i>", "{\\i0}")
        # 删除 <i> 和 </i>
        merged_text = merged_text.replace("<i>", "").replace("</i>", "")
        
        merged_entries.append((eng_start, eng_end, merged_text))
    return merged_entries

def write_ass(merged_entries, output_path, filename):
    """
    写入 ASS 文件，包含头部信息和合并后的字幕，title为文件名，comment为日期信息yyyy-mm-dd
    """
    today = date.today().isoformat()
    header = (
        "[Script Info]\n"
        f"Title: {filename}\n"
        "Author: lns103\n"
        f"Comment: {today} made by my SRT merge script\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1920\n"
        "PlayResY: 1080\n"
        "Timer: 100.0000\n"
        "WrapStyle: 0\n"
        "YCbCr Matrix: TV.709\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Chinese, 黑体, 60, &H00EEEEEE, &HF0000000, &H00000000, &H32000000, 0, 0, 0, 0, 100, 100, 0, 0, 1, 1.5, 0, 2, 18, 18, 18, 1\n"
        "Style: Original, Arial, 40, &H00EEEEEE, &HF0000000, &H00000000, &H32000000, 0, 0, 0, 0, 100, 100, 0, 0, 1, 1.5, 0, 2, 18, 18, 18, 1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(header)
        for start, end, text in merged_entries:
            line = f"Dialogue: 0,{start},{end},Chinese,,0,0,0,,{text}\n"
            f.write(line)

def merge_and_save(eng_path, zh_path, output_path, filename):
    """
    合并单个中英文字幕对并保存为 ASS
    """
    try:
        eng_entries = parse_srt(eng_path)
        zh_entries = parse_srt(zh_path)
        merged_entries = merge_srt(eng_entries, zh_entries)
        write_ass(merged_entries, output_path, filename)
        print(f"生成文件: {output_path}")
        return True, f"生成文件: {os.path.basename(output_path)}"
    except Exception as e:
        print(f"处理 {filename} 时出错: {e}")
        return False, f"处理失败 {filename}: {e}"

def process_directory(folder):
    """
    处理目录下的双语字幕合并
    """
    results = []
    # 查找文件夹下所有 *.srt 文件
    files = [f for f in os.listdir(folder) if f.endswith(".srt")]
    # 筛选英文文件（假设不包含 .zh）
    eng_files = [f for f in files if not f.endswith(".zh.srt")]
    
    # 确保输出目录存在
    output_folder = os.path.join(folder, "merge")
    os.makedirs(output_folder, exist_ok=True)
    
    for eng_file in eng_files:
        base, ext = os.path.splitext(eng_file)
        zh_file = f"{base}.zh.srt"
        eng_path = os.path.join(folder, eng_file)
        zh_path = os.path.join(folder, zh_file)
        if not os.path.exists(zh_path):
            print(f"对应的中文文件不存在: {zh_path}")
            if os.path.exists(os.path.join(folder, f"{base}.zh.srt")):
                 zh_path = os.path.join(folder, f"{base}.zh.srt")
            else:
                 results.append(f"跳过 {eng_file}: 找不到对应的中文文件")
                 continue
        
        # 输出文件名格式：xxx.zh&en.ass
        output_filename = f"{base}.zh&en.ass"
        output_path = os.path.join(output_folder, output_filename)
        
        success, msg = merge_and_save(eng_path, zh_path, output_path, base)
        results.append(msg)
        
    return results

def main():
    if len(sys.argv) < 2:
        print("用法: python merge_srt.py <srt文件所在文件夹>")
        sys.exit(1)
    
    folder = sys.argv[1]
    process_directory(folder)

if __name__ == "__main__":
    main()
