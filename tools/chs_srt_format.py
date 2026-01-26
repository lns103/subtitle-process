import re
import argparse
import os

def format_zh_text(zh_text: str) -> str:
    # 替换常见标点符号格式
    zh_text = zh_text.replace("，", "  ").replace("。", "  ").replace("！", "! ").replace("？", "? ")

    # 去掉标点前的多余空格
    zh_text = re.sub(r"\s+\"", "\"", zh_text)
    zh_text = re.sub(r"\s+\'", "\'", zh_text)
    zh_text = re.sub(r"\s+」", "」", zh_text)
    zh_text = re.sub(r"\s+》", "》", zh_text)
    zh_text = re.sub(r"\s+\”", "”", zh_text)

    # 去掉首尾空格
    return zh_text.strip()


def process_srt(input_file: str, output_file: str):
    with open(input_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    formatted_lines = []
    for line in lines:
        # 判断是不是字幕序号或时间轴
        if re.match(r"^\d+$", line.strip()) or re.match(r"^\d{2}:\d{2}:\d{2},\d{3}", line.strip()):
            formatted_lines.append(line)
        else:
            formatted_lines.append(format_zh_text(line) + "\n")

    with open(output_file, "w", encoding="utf-8") as f:
        f.writelines(formatted_lines)
    return True, f"格式化完成: {output_file}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="格式化 SRT 字幕文件")
    parser.add_argument("input", help="输入的 SRT 文件路径")
    parser.add_argument("-o", "--output", help="输出文件路径（可选，不指定则保存为 input_formatted.srt）")

    args = parser.parse_args()

    input_path = args.input
    if args.output:
        output_path = args.output
    else:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_formatted{ext}"

    process_srt(input_path, output_path)
    print(f"格式化完成，结果已保存到 {output_path}")
