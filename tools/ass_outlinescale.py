#!/usr/bin/env python3
import argparse
import re

def process_dialogue_inline_styles(line, scale_factor):
    def replace_tag(match):
        tag = match.group(1)
        value_str = match.group(2)
        try:
            value = float(value_str)
        except ValueError:
            return match.group(0)  # 返回原始匹配
        scaled_value = value * scale_factor
        if scaled_value.is_integer():
            formatted_value = str(int(scaled_value))
        else:
            # 格式化为两位小数，并移除尾随零和点
            formatted_value = "{:.2f}".format(scaled_value).rstrip('0').rstrip('.')
        return f'\\{tag}{formatted_value}'
    
    # 使用正则表达式替换所有\bord和\shad标签，不区分大小写
    processed_line = re.sub(
        r'\\(bord|shad)(\d+\.?\d*)',
        replace_tag,
        line,
        flags=re.IGNORECASE
    )
    return processed_line

def process_ass_file(input_path, output_path):
    default_playres_x = 384
    default_playres_y = 288

    # 尝试多种编码读取文件
    encodings = ['utf-8-sig', 'utf-16', 'gbk']
    for enc in encodings:
        try:
            with open(input_path, 'r', encoding=enc) as f:
                lines = f.readlines()
            break
        except UnicodeDecodeError:
            continue
    else:
        raise UnicodeDecodeError(f"无法用以下编码读取文件: {encodings}")

    playres_x = None
    playres_y = None
    in_script_info = False
    scaled_border_found = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            section = stripped.lower()
            in_script_info = (section == "[script info]")
        if in_script_info:
            if stripped.lower().startswith("playresx:"):
                try:
                    playres_x = int(stripped.split(":", 1)[1].strip())
                except Exception:
                    pass
            if stripped.lower().startswith("playresy:"):
                try:
                    playres_y = int(stripped.split(":", 1)[1].strip())
                except Exception:
                    pass
            if stripped.lower().startswith("scaledborderandshadow: yes"):
                scaled_border_found = True
                break
            if stripped.lower().startswith("scaledborderandshadow:"):
                line = "ScaledBorderAndShadow: yes\n"
        new_lines.append(line)
        
    if scaled_border_found:
        print(f"No edit: {output_path}")
        return False, f"无需修改: {os.path.basename(output_path)}"

    script_info_start = None
    script_info_end = None
    for i, line in enumerate(new_lines):
        if line.strip().lower() == "[script info]":
            script_info_start = i
            continue
        if script_info_start is not None and line.strip().startswith('[') and line.strip().endswith(']'):
            script_info_end = i
            break
    if script_info_start is not None:
        found_scaled = any(l.strip().lower().startswith("scaledborderandshadow:") 
                           for l in new_lines[script_info_start: script_info_end if script_info_end is not None else len(new_lines)])
        if not found_scaled:
            new_lines.insert(script_info_start + 1, "ScaledBorderAndShadow: yes\n")

    if playres_x is None or playres_x == 0:
        playres_x = default_playres_x
    if playres_y is None or playres_y == 0:
        playres_y = default_playres_y
    scale_factor = playres_y / 1080

    output_lines = []
    in_styles = False
    styles_format = []
    outline_index = None
    shadow_index = None

    for line in new_lines:
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            section = stripped.lower()
            in_styles = (section == "[v4+ styles]")
        if in_styles:
            if stripped.lower().startswith("format:"):
                fields = stripped[len("format:"):].split(",")
                styles_format = [f.strip().lower() for f in fields]
                try:
                    outline_index = styles_format.index("outline")
                    shadow_index = styles_format.index("shadow")
                except ValueError:
                    outline_index = None
                    shadow_index = None
                output_lines.append(line)
                continue
            if stripped.lower().startswith("style:") and styles_format:
                prefix, rest = line.split(":", 1)
                values = [v.strip() for v in rest.split(",")]
                if outline_index is not None and shadow_index is not None:
                    try:
                        original_outline = float(values[outline_index])
                        original_shadow = float(values[shadow_index])
                        new_outline = original_outline * scale_factor
                        new_shadow = original_shadow * scale_factor
                        values[outline_index] = str(int(new_outline)) if new_outline.is_integer() else f"{new_outline:.2f}"
                        values[shadow_index] = str(int(new_shadow)) if new_shadow.is_integer() else f"{new_shadow:.2f}"
                    except Exception:
                        pass
                new_line = prefix + ": " + ", ".join(values) + "\n"
                output_lines.append(new_line)
                continue
        output_lines.append(line)

    # 处理对话行中的内联样式
    for i in range(len(output_lines)):
        line = output_lines[i]
        if line.lower().startswith('dialogue:'):
            processed_line = process_dialogue_inline_styles(line, scale_factor)
            output_lines[i] = processed_line

    with open(output_path, 'w', encoding='utf-8', newline="\n") as f:
        f.writelines(output_lines)
    print(f"Scaled: {output_path}")
    return True, f"已缩放: {os.path.basename(output_path)}"

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="调整 ASS 字幕文件：设置 ScaledBorderAndShadow 为 yes，并按 1080p 分辨率缩放边框和阴影参数。"
    )
    parser.add_argument("input", help="输入的 ASS 字幕文件路径")
    # parser.add_argument("output", help="输出的 ASS 字幕文件路径")
    args = parser.parse_args()
    process_ass_file(args.input, args.input)