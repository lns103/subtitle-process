import argparse
import os
import re
import sys

# 获取指定路径下所有以特定后缀结尾的文件存到列表中
def get_files_with_extensions(path, extensions):
    file_list = []
    for file in os.listdir(path):
        if file.lower().endswith(tuple(extensions)):
            file_list.append(os.path.basename(file))
    return file_list

# 识别并提取文件名中的S\d\dE\d\d
def extract_season_episode(filename):
    pattern = r"(?i)S(\d+)E(\d+)"
    match = re.search(pattern, filename)
    if match:
        season = match.group(1)
        episode = match.group(2)
        return season, episode
    else:
        return None

def case_insensitive_replace(s, old, new):
    pattern = re.compile(old, re.IGNORECASE)
    return pattern.sub(new, s)

# 将season和episode匹配的sub重命名为video文件名
def rename_subtitle_files(video_file_list, subtitle_file_list, path):
    number = 0
    for video_file in video_file_list:
        video_filename = os.path.basename(video_file)
        try:
            video_season, video_episode = extract_season_episode(video_filename)
            for subtitle_file in subtitle_file_list:
                subtitle_filename = os.path.basename(subtitle_file)
                subtitle_season, subtitle_episode = extract_season_episode(subtitle_filename)
                if int(video_season) == int(subtitle_season) and int(video_episode) == int(subtitle_episode):
                    # new_subtitle_filename = os.path.splitext(video_filename)[0] + os.path.splitext(subtitle_filename)[1].replace('ssa', 'ass')
                    new_subtitle_filename = os.path.splitext(video_filename)[0] + case_insensitive_replace(os.path.splitext(subtitle_filename)[1], 'ssa', 'ass')
                    os.rename(path + '/' + subtitle_file, path + '/' + new_subtitle_filename)
                    if subtitle_filename != new_subtitle_filename:
                        number = number + 1
                        print("\033[0m" + str(number) + "." + subtitle_filename + "\n  \033[1m →" + new_subtitle_filename + "\033[0m")
        finally:
            pass
    return number

# # 从命令行参数获取路径
# path = sys.argv[1].replace('"', '')
# path = path.replace('\\','/')

video_extensions = [".mp4", ".mkv"]
subtitle_extensions = [".srt", ".ass", ".ssa", ".sup"]

def process_directory(folder):
    """批量重命名目录下的字幕文件"""
    video_file_list = get_files_with_extensions(folder, video_extensions)
    subtitle_file_list = get_files_with_extensions(folder, subtitle_extensions)
    
    # 重命名匹配的字幕文件
    count = rename_subtitle_files(video_file_list, subtitle_file_list, folder)
    
    msg = f"Find {len(video_file_list)} videos and {len(subtitle_file_list)} subs, rename {count} subs."
    print(msg)
    return count, msg

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批量修改文件夹中的所有字幕文件名称")
    parser.add_argument("folder", help="要处理的文件夹路径")
    args = parser.parse_args()

    process_directory(args.folder)
