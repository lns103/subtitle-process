import argparse
import os
import re
import sys
from collections import defaultdict

# 获取指定路径下所有以特定后缀结尾的文件存到列表中
def get_files_with_extensions(path, extensions):
    file_list = []
    for file in os.listdir(path):
        if file.lower().endswith(tuple(extensions)):
            file_list.append(os.path.basename(file))
    return file_list

# 识别并提取文件名中的SxxExx, 01x01, 或 TxxCxx
def extract_season_episode(filename):
    patterns = [
        r"(?i)S(\d+)E(\d+)",
        r"(?i)(\d+)x(\d+)",
        r"(?i)T(\d+)C(\d+)"
    ]
    for pattern in patterns:
        match = re.search(pattern, filename)
        if match:
            season = match.group(1)
            episode = match.group(2)
            return season, episode
    return None

def case_insensitive_replace(s, old, new):
    pattern = re.compile(old, re.IGNORECASE)
    return pattern.sub(new, s)

def extract_original_suffix(s_name):
    name_without_ext, _ = os.path.splitext(s_name)
    parts = name_without_ext.split('.')
    if len(parts) == 1:
        return ""
    
    last_part = parts[-1]
    
    def is_valid_part(part):
        return len(part) <= 10 and not extract_season_episode(part)

    if last_part.isdigit() and len(parts) >= 3:
        second_last = parts[-2]
        if is_valid_part(second_last):
            return f".{second_last}.{last_part}"
        elif is_valid_part(last_part):
            return f".{last_part}"
    elif is_valid_part(last_part):
        return f".{last_part}"
        
    return ""

def rename_subtitle_files_by_paths(video_full_paths, subtitle_full_paths, suffix=""):
    count = 0
    # 建立视频文件字典 SxxExx -> full_path
    video_map = {}
    for v_path in video_full_paths:
        v_name = os.path.basename(v_path)
        se = extract_season_episode(v_name)
        if se:
            video_map[se] = v_path # (season, episode) -> path

    # 按照season和episode分组字幕文件
    matched_subs = defaultdict(list)
    for s_path in subtitle_full_paths:
        s_name = os.path.basename(s_path)
        se = extract_season_episode(s_name)
        if se and se in video_map:
            matched_subs[se].append(s_path)

    used_names = set()

    for se, s_paths in matched_subs.items():
        v_path = video_map[se]
        v_name = os.path.basename(v_path)
        v_name_no_ext = os.path.splitext(v_name)[0]
        
        # 按后缀分组，检查是否有相同格式的多个字幕
        subs_by_ext = defaultdict(list)
        for p in s_paths:
            s_ext = os.path.splitext(p)[1]
            new_ext = case_insensitive_replace(s_ext, 'ssa', 'ass')
            subs_by_ext[new_ext.lower()].append(p)
            
        for ext_lower, paths_for_ext in subs_by_ext.items():
            multiple = len(paths_for_ext) > 1
            
            for s_path in paths_for_ext:
                s_name = os.path.basename(s_path)
                s_dir = os.path.dirname(s_path)
                s_ext = os.path.splitext(s_name)[1]
                new_ext = case_insensitive_replace(s_ext, 'ssa', 'ass')
                
                orig_suffix = extract_original_suffix(s_name) if multiple else ""
                
                if orig_suffix:
                    base_new_name = v_name_no_ext + orig_suffix
                else:
                    base_new_name = v_name_no_ext + suffix
                
                new_sub_full_path = os.path.join(s_dir, base_new_name + new_ext)
                
                # 防冲突处理
                dedup_idx = 1
                while new_sub_full_path.lower() in used_names or (os.path.exists(new_sub_full_path) and os.path.normcase(new_sub_full_path) != os.path.normcase(s_path)):
                    dedup_name = f"{base_new_name}.{dedup_idx}{new_ext}"
                    new_sub_full_path = os.path.join(s_dir, dedup_name)
                    dedup_idx += 1
                
                used_names.add(new_sub_full_path.lower())
                
                if os.path.normcase(s_path) != os.path.normcase(new_sub_full_path):
                    try:
                        os.rename(s_path, new_sub_full_path)
                        count += 1
                        new_sub_name = os.path.basename(new_sub_full_path)
                        print(f"\033[0m{count}. {s_name}\n  \033[1m -> {new_sub_name}\033[0m")
                    except OSError as e:
                        print(f"Error renaming {s_name}: {e}")
                    
    return count

# # 从命令行参数获取路径
# path = sys.argv[1].replace('"', '')
# path = path.replace('\\','/')

video_extensions = [".mp4", ".mkv"]
subtitle_extensions = [".srt", ".ass", ".ssa", ".sup", ".vtt"]

def process_directory(folder, suffix=""):
    """批量重命名目录下的字幕文件"""
    v_files = get_files_with_extensions(folder, video_extensions)
    s_files = get_files_with_extensions(folder, subtitle_extensions)
    
    video_file_list = [os.path.join(folder, f) for f in v_files]
    subtitle_file_list = [os.path.join(folder, f) for f in s_files]
    
    # 重命名匹配的字幕文件
    count = rename_subtitle_files_by_paths(video_file_list, subtitle_file_list, suffix)
    
    msg = f"Find {len(video_file_list)} videos and {len(subtitle_file_list)} subs, rename {count} subs."
    print(msg)
    return count, msg

def process_files(file_list, suffix=""):
    """
    处理给定的文件列表中的字幕重命名
    :param file_list: 文件路径列表
    """
    video_files = []
    subtitle_files = []
    
    for f in file_list:
        ext = os.path.splitext(f)[1].lower()
        if ext in video_extensions:
            video_files.append(f)
        elif ext in subtitle_extensions:
            subtitle_files.append(f)
            
    count = rename_subtitle_files_by_paths(video_files, subtitle_files, suffix)
    msg = f"In list: found {len(video_files)} videos and {len(subtitle_files)} subs, rename {count} subs."
    return count, msg

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批量修改文件夹中的所有字幕文件名称")
    parser.add_argument("folder", help="要处理的文件夹路径")
    args = parser.parse_args()

    process_directory(args.folder)
