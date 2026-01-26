#!/usr/bin/env python3
import os
import subprocess
import argparse

def process_ass_files_in_directory(directory):
    # 确保目录存在
    if not os.path.isdir(directory):
        print(f"错误: 指定的路径 '{directory}' 不是一个有效的目录。")
        return

    # 获取目录下所有 .ass 文件
    ass_files = [f for f in os.listdir(directory) if f.lower().endswith('.ass')]
    
    if not ass_files:
        print("未找到任何 .ass 文件。")
        return

    print(f"找到 {len(ass_files)} 个 ASS 字幕文件，开始处理...")

    for ass_file in ass_files:
        input_path = os.path.join(directory, ass_file)
        # temp_output_path = input_path + ".temp"  # 临时文件

        # print(f"处理文件: {ass_file} ...", end=" ")
        
        # 调用 ass_outlinescale.py 进行处理
        try:
            subprocess.run(["python", "./ass_outlinescale.py", input_path], check=True)
            # 处理成功，替换原文件
            # os.replace(temp_output_path, input_path)
            # print("描边缩放完成 ✅")
        except subprocess.CalledProcessError:
            print("描边缩放失败 ❌")
            
    try:
        subprocess.run(["python", "./rename_sub.py", directory], check=True)
        print("重命名完成 ✅")
    except subprocess.CalledProcessError:
        print("重命名失败 ❌")
    print("所有文件处理完成！")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批量修改文件夹中的所有 ASS 字幕文件，调整 Outline 和 Shadow。")
    parser.add_argument("folder", help="要处理的文件夹路径")
    args = parser.parse_args()

    process_ass_files_in_directory(args.folder)
