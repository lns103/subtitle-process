import re
import sys
import os
import subprocess

MAX_SUBTITLE_LENGTH = 95  # 最大字幕长度

def merge_subtitles(blocks):
    """合并短字幕块"""
    if not blocks:
        return []

    merged_blocks = []
    merge_count = 0
    current_timestamp, current_text = blocks[0]

    for next_timestamp, next_text in blocks[1:]:
        current_text_stripped = current_text.rstrip()
        next_text_stripped = next_text.lstrip()

        # 去除当前文本结尾破折号（可选）
        if current_text_stripped.endswith('-'):
            current_text_stripped = current_text_stripped[:-1].rstrip()

        proposed_merged_text = current_text_stripped + " " + next_text_stripped

        # 检查上一句结束和下一句开始的时间戳差距
        time_pattern = r'(\d{2}):(\d{2}):(\d{2}),(\d{3})'
        current_match = re.search(time_pattern, current_timestamp.split(' --> ')[1])
        next_match = re.search(time_pattern, next_timestamp.split(' --> ')[0])

        current_end_time = (
            int(current_match.group(1)) * 3600 +
            int(current_match.group(2)) * 60 +
            int(current_match.group(3)) +
            int(current_match.group(4)) / 1000
        )
        next_start_time = (
            int(next_match.group(1)) * 3600 +
            int(next_match.group(2)) * 60 +
            int(next_match.group(3)) +
            int(next_match.group(4)) / 1000
        )

        # 检查合并条件
        if (current_text and
            (current_text.rstrip()[-1] not in ".!?" or current_text.rstrip().endswith('-')) and
            re.match(r'[a-z0-9]', next_text_stripped) and
            len(proposed_merged_text) < MAX_SUBTITLE_LENGTH and
            (next_start_time - current_end_time) <= 0.6):  # 时间差距小于等于600毫秒

            # 更新文本（去掉破折号后合并）
            current_text = proposed_merged_text

            # 更新时间戳：当前字幕起始时间不变，结束时间取下一字幕的结束时间
            current_parts = current_timestamp.split()
            next_parts = next_timestamp.split()
            if len(current_parts) >= 3 and len(next_parts) >= 3:
                current_timestamp = f"{current_parts[0]} --> {next_parts[2]}"
            
            merge_count += 1
        else:
            merged_blocks.append((current_timestamp, current_text))
            current_timestamp, current_text = next_timestamp, next_text

    merged_blocks.append((current_timestamp, current_text))
    return merged_blocks, merge_count


def process_subtitles_content(content, skip_merge=False, clean_uppercase=False, clean_person=True):
    """处理字幕内容字符串"""
    blocks = re.split(r'\n\s*\n', content.strip())  # 以空行分割字幕块
    processed_blocks = []
    
    stats = {"brackets": 0, "person_hints": 0, "tags": 0, "merged": 0, "uppercase": 0}
    
    for block in blocks:
        lines = block.splitlines()

        # 判断行中是否包含时间戳标识 '-->'
        if len(lines) > 0 and '-->' in lines[0]:
            timestamp_line = lines[0]
            text_lines = lines[1:]
        else:
            if len(lines) < 3:
                continue
            # 对于编号存在的情况，第一行为序号，第二行为时间戳，后面为文本
            timestamp_line = lines[1]
            text_lines = lines[2:]
        
        # 如果开启了 clean_uppercase，逐行判断并清理大写行
        if clean_uppercase:
            new_text_lines = []
            for line in text_lines:
                # 移除非字母特殊格式（例如 {\an8} 和 <i> 等）以检验纯文本内容
                text_without_tags = re.sub(r'\{[^{}]*\}', '', line)
                text_without_tags = re.sub(r'<[^>]*>', '', text_without_tags).strip()
                
                # 核心判断逻辑：
                # 1. stripped_line.isupper(): 确保行内包含字母且全部为大写
                # 2. not re.search(r'[.,\/#!$%\^&\*;:{}=\-_`~()?"\']', stripped_line): 确保不包含任何常见标点符号
                # 3. 允许纯数字或不含字母的特殊行通过（即当isupper()为False时通过，不进行大写清除）
                if text_without_tags.isupper() and not re.search(r'[.,\/#!$%\^&\*;:{}=\-_`~()?"\']', text_without_tags):
                    stats["uppercase"] += 1
                    # 剥离大写内容，仅保留该行中的标签/控制符
                    processed_line = line.replace(text_without_tags, '', 1)
                else:
                    processed_line = line
                new_text_lines.append(processed_line)
            text_lines = new_text_lines

        # 人名提示识别正则：
        # 1. 冒号前被 [] 或 () 包裹的人名，例如 [BEN]:, [Ben]:, (John):, (Doctor Smith):
        # 2. 冒号前为全大写/含大写的多词名称，例如 OLD MAN:, MAN #1:
        # 3. 冒号前为单个单词，例如 Ben:, Alice:, Doctor:, 旁白:
        # 4. 支持行首破折号（保留）以及行内破折号后的提示
        speaker_pattern = re.compile(
            r'(^(\s*-\s*)?|\s+-\s+)'
            r'(?:'
                r'\[[^\]\r\n]{1,40}\]'
                r'|\([^)\r\n]{1,40}\)'
                r'|(?=.*[A-Z])[A-Z0-9\s#\.\-_&\'/,\+\u00A0]{1,30}'
                r'|(?!\d+$)[^\s:：]{1,30}'
            r')'
            r'\s*[:：](?!\d|//)\s*'
        )

        def _clean_person_in_lines(lines_list):
            nonlocal stats
            res_lines = []
            for l in lines_list:
                l_stripped = l.strip()
                if not l_stripped:
                    continue
                new_l, count = speaker_pattern.subn(r'\1', l_stripped)
                if count > 0:
                    stats["person_hints"] += count
                    res_lines.append(new_l)
                else:
                    res_lines.append(l_stripped)
            return res_lines

        # 如果开启了 clean_person，优先在行级别清理人名提示（防止带括号的人名如 [BEN]: 中的括号被提前删除留下孤立冒号）
        if clean_person:
            cleaned_lines = _clean_person_in_lines(text_lines)
            text = '\n'.join(cleaned_lines)
        else:
            text = '\n'.join(text_lines)

        # 移除所有括号内容（包括跨行的）
        # 统计移除数量
        text, n1 = re.subn(r'\(.*?\)', '', text, flags=re.DOTALL)
        text, n2 = re.subn(r'\[.*?\]', '', text, flags=re.DOTALL)
        stats["brackets"] += (n1 + n2)

        # 如果删完只剩 -，就跳过
        if text.strip() in ('-', '-'):
            continue

        # 如果在括号移除后（如 "(music) Ben: Hello" 或 "MAN (on TV): Hello"），暴露出新的人名提示，进行二次清理
        if clean_person:
            lines = text.split('\n')
            cleaned_lines = _clean_person_in_lines(lines)
            text = ' '.join(cleaned_lines)
        else:
            text = text.replace('\n', ' ')
        
        # 统计破折号 `- ` 出现次数，仅开头出现一次时移除
        dash_count = text.count('- ')
        if dash_count == 1:
            if text.startswith('- '):
                text = text.replace('- ', '', 1)

        # 移除 <b> </b> <i> </i> 和 {\an2} 标签
        text, n1 = re.subn(r'<b>|</b>', '', text)
        text, n2 = re.subn(r'<i>|</i>', '', text)
        text, n3 = re.subn(r'\{\\an2\}', '', text)
        stats["tags"] += (n1 + n2 + n3)
        
        # 规范空格
        text = re.sub(r'\s+', ' ', text).strip()

        # 判断处理后的文本是否仅包含 {\an8} 这样的控制符（或其它花括号/HTML标签）
        final_stripped = re.sub(r'\{[^{}]*\}', '', text)
        final_stripped = re.sub(r'<[^>]*>', '', final_stripped).strip()
        if not final_stripped:
            continue

        if text:
            processed_blocks.append((timestamp_line, text))
    
    # 对处理好的字幕块执行合并操作（可通过 skip_merge 跳过）
    if skip_merge:
        merged_blocks = processed_blocks
    else:
        merged_blocks, merged_count = merge_subtitles(processed_blocks)
        stats["merged"] = merged_count
    
    output_lines = []
    for i, (timestamp, text) in enumerate(merged_blocks, start=1):
        output_lines.append(str(i))
        output_lines.append(timestamp)
        output_lines.append(text)
        output_lines.append('')

    return '\n'.join(output_lines).strip(), stats

def process_single_file(file_path, skip_merge=False, clean_uppercase=False, clean_person=True):
    """处理单个文件"""
    try:
        original_path = file_path
        is_vtt = file_path.lower().endswith('.vtt')
        
        if is_vtt:
            srt_path = os.path.splitext(file_path)[0] + '.srt'
            try:
                subprocess.run(['ffmpeg', '-i', file_path, '-y', srt_path],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                file_path = srt_path
            except Exception as e:
                print(f"VTT转换失败 {original_path}: {e}")
                return False, f"VTT转换失败 {os.path.basename(original_path)}: {e}"
                
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            content = f.read()
        
        processed_content, stats = process_subtitles_content(content, skip_merge=skip_merge, clean_uppercase=clean_uppercase, clean_person=clean_person)
        
        with open(file_path, 'w', encoding='utf-8', newline="\n") as f:
            f.write(processed_content)
        
        # 格式化统计信息用于返回
        # 仅显示非零的统计
        stats_str_parts = []
        if stats['brackets'] > 0: stats_str_parts.append(f"括号-{stats['brackets']}")
        if stats['person_hints'] > 0: stats_str_parts.append(f"人物-{stats['person_hints']}")
        if stats['tags'] > 0: stats_str_parts.append(f"标签-{stats['tags']}")
        if stats['merged'] > 0: stats_str_parts.append(f"合并-{stats['merged']}")
        if 'uppercase' in stats and stats['uppercase'] > 0: stats_str_parts.append(f"大写行-{stats['uppercase']}")
        
        stats_msg = f" ({', '.join(stats_str_parts)})" if stats_str_parts else ""
        
        prefix = "VTT转SRT并清理完成" if is_vtt else "处理完成"
        print(f"{prefix}: {file_path}{stats_msg}")
        return True, f"{prefix}: {os.path.basename(file_path)}{stats_msg}"
    except Exception as e:
        print(f"处理失败 {file_path}: {e}")
        return False, f"处理失败 {os.path.basename(file_path)}: {e}"

def process_directory(directory, skip_merge=False, clean_uppercase=False, clean_person=True):
    """处理目录下的所有 srt 文件"""
    results = []
    for filename in os.listdir(directory):
        if filename.lower().endswith(".srt") or filename.lower().endswith(".vtt"): 
            file_path = os.path.join(directory, filename)
            success, msg = process_single_file(file_path, skip_merge=skip_merge, clean_uppercase=clean_uppercase, clean_person=clean_person)
            results.append(msg)
    return results

def main():
    # 支持可选参数 --skip 来跳过字幕块合并操作
    # 以及 --clean-uppercase 和 --no-clean-person
    args = sys.argv[1:]
    if not args:
        print("Usage: python srt_process.py <directory> [--skip] [--clean-uppercase] [--no-clean-person]")
        sys.exit(1)

    skip_merge = False
    if '--skip' in args:
        skip_merge = True
        args = [a for a in args if a != '--skip']

    clean_uppercase = False
    if '--clean-uppercase' in args:
        clean_uppercase = True
        args = [a for a in args if a != '--clean-uppercase']

    clean_person = True
    if '--no-clean-person' in args:
        clean_person = False
        args = [a for a in args if a != '--no-clean-person']

    if not args:
        print("Usage: python srt_process.py <directory> [--skip] [--clean-uppercase] [--no-clean-person]")
        sys.exit(1)

    directory = args[0]
    if not os.path.isdir(directory):
        print("错误: 目录不存在")
        sys.exit(1)
    
    process_directory(directory, skip_merge=skip_merge, clean_uppercase=clean_uppercase, clean_person=clean_person)
    print("所有字幕处理完成！")

if __name__ == '__main__':
    main()
