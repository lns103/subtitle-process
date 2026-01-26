import os
import sys

# 尝试相对导入，如果失败则尝试添加路径后导入
try:
    from . import srt_process
    from . import merge_srt
    from . import rename_sub
    from . import ass_outlinescale
    from . import chs_srt_format
    from . import terms_merge
except ImportError:
    import srt_process
    import merge_srt
    import rename_sub
    import ass_outlinescale
    import chs_srt_format
    import terms_merge

class SubtitleTool:
    """
    统一的字幕处理接口类
    """

    @staticmethod
    def clean_srt(paths, skip_merge=False):
        """
        清理 SRT 字幕 (去除多余标点、合并短句等)
        :param paths: 文件路径列表或目录路径
        :param skip_merge: 是否跳过合并字幕块
        :return: Generator yielding result messages
        """
        if isinstance(paths, str):
            if os.path.isdir(paths):
                # 处理目录
                results = srt_process.process_directory(paths, skip_merge=skip_merge)
                for msg in results:
                    yield msg
                return
            else:
                paths = [paths]
        
        for p in paths:
            if os.path.isdir(p):
                 results = srt_process.process_directory(p, skip_merge=skip_merge)
                 for msg in results:
                    yield msg
            elif os.path.isfile(p):
                success, msg = srt_process.process_single_file(p, skip_merge=skip_merge)
                yield msg

    @staticmethod
    def format_chs_srt(paths):
        """
        格式化中文字幕 (标点处理)
        :param paths: 文件路径列表
        :return: Generator yielding result messages
        """
        if isinstance(paths, str):
            paths = [paths]
        
        for p in paths:
            if os.path.isdir(p):
                # 遍历目录下的 .srt 文件
                for f in os.listdir(p):
                    if f.endswith(".srt"):
                        full_path = os.path.join(p, f)
                        success, msg = chs_srt_format.process_srt(full_path, full_path)
                        yield msg
            elif os.path.isfile(p):
                success, msg = chs_srt_format.process_srt(p, p)
                yield msg

    @staticmethod
    def merge_bilingual_srt(folder):
        """
        合并双语字幕 (文件夹下的 英文.srt 和 中文.srt)
        :param folder: 文件夹路径
        :return: Generator yielding result messages
        """
        if not os.path.isdir(folder):
            yield f"错误: 不是一个文件夹: {folder}"
            return
            
        results = merge_srt.process_directory(folder)
        for msg in results:
            yield msg

    @staticmethod
    def rename_subtitles(folder):
        """
        重命名字幕文件以匹配视频文件
        :param folder: 文件夹路径
        :return: Generator yielding result messages
        """
        if not os.path.isdir(folder):
            yield f"错误: 不是一个文件夹: {folder}"
            return

        count, msg = rename_sub.process_directory(folder)
        yield msg

    @staticmethod
    def scale_ass_outline(paths):
        """
        缩放 ASS 字幕边框 (针对 1080p 优化)
        :param paths: 文件路径列表
        :return: Generator yielding result messages
        """
        if isinstance(paths, str):
            paths = [paths]
            
        for p in paths:
            if os.path.isdir(p):
                # 遍历处理目录下的 ass
                for f in os.listdir(p):
                    if f.lower().endswith(".ass"):
                        full_path = os.path.join(p, f)
                        success, msg = ass_outlinescale.process_ass_file(full_path, full_path)
                        yield msg
            elif os.path.isfile(p):
                success, msg = ass_outlinescale.process_ass_file(p, p)
                yield msg

    @staticmethod
    def merge_terms(file1, file2, output):
        """
        合并术语表 JSON
        """
        success, msg = terms_merge.merge_json_files(file1, file2, output)
        yield msg
