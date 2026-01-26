import json
import argparse

def merge_json_files(file1, file2, output_file):
    """合并两个 JSON 文件，src 相同时保留第一个文件的条目"""
    try:
        # 读取两个 JSON 文件
        with open(file1, 'r', encoding='utf-8') as f:
            data1 = json.load(f)
        with open(file2, 'r', encoding='utf-8') as f:
            data2 = json.load(f)
    except Exception as e:
        print(f"文件读取失败: {e}")
        return False, f"文件读取失败: {e}"

    # 创建 src 值的集合用于快速查找
    src_set = {item["src"] for item in data1}
    
    # 过滤 file2 中 src 不重复的条目
    unique_data2 = [item for item in data2 if item["src"] not in src_set]
    
    # 合并结果（保留 file1 的所有内容 + file2 的独特内容）
    merged_data = data1 + unique_data2

    # 写入输出文件
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(merged_data, f, ensure_ascii=False, indent=2)
        print(f"合并完成！结果已保存至: {output_file}")
        return True, f"合并完成: {output_file}"
    except Exception as e:
        print(f"结果写入失败: {e}")
        return False, f"结果写入失败: {e}"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='合并两个JSON术语表')
    parser.add_argument('file1', help='第一个JSON文件路径')
    parser.add_argument('file2', help='第二个JSON文件路径')
    parser.add_argument('output', help='输出文件路径')
    
    args = parser.parse_args()
    
    merge_json_files(args.file1, args.file2, args.output)