import os
import sys

# 尝试相对导入，如果失败则尝试添加路径后导入
try:
    from . import srt_process
    from . import merge_srt
    from . import rename_sub
    from . import ass_outlinescale
    from . import chs_srt_format

    from . import subtitle_extractor
    from . import fps_converter
except ImportError:
    import srt_process
    import merge_srt
    import rename_sub
    import ass_outlinescale
    import chs_srt_format

    import subtitle_extractor
    import fps_converter

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
    def merge_bilingual_srt(paths):
        """
        合并双语字幕 (文件夹下的 英文.srt 和 中文.srt)
        :param paths: 文件夹路径或文件路径列表
        :return: Generator yielding result messages
        """
        if isinstance(paths, str):
            if os.path.isdir(paths):
                # 兼容旧调用 (虽然后面我们会改 UI，但保持健壮性)
                 paths = [paths]
            else:
                 # 单个文件
                 paths = [paths]
                 
        # 分离目录和文件
        dirs = set()
        files = []
        for p in paths:
            if os.path.isdir(p):
                dirs.add(p)
            elif os.path.isfile(p):
                files.append(p)
                
        # 处理目录
        for d in dirs:
            results = merge_srt.process_directory(d)
            for msg in results:
                yield msg
                
        # 处理文件列表
        if files:
            results = merge_srt.process_files(files)
            for msg in results:
                yield msg

    @staticmethod
    def rename_subtitles(paths):
        """
        重命名字幕文件以匹配视频文件
        :param paths: 文件夹路径或文件路径列表
        :return: Generator yielding result messages
        """
        if isinstance(paths, str):
            if os.path.isdir(paths):
                paths = [paths]
            else:
                paths = [paths]

        # 分离目录和文件
        dirs = set()
        files = []
        for p in paths:
            if os.path.isdir(p):
                dirs.add(p)
            elif os.path.isfile(p):
                files.append(p)
                
        # 处理目录
        for d in dirs:
            count, msg = rename_sub.process_directory(d)
            yield msg
            
        # 处理文件列表
        if files:
            count, msg = rename_sub.process_files(files)
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
    def get_video_info(filepath):
        """
        获取视频字幕信息
        """
        return subtitle_extractor.SubtitleExtractor.get_media_info(filepath)

    @staticmethod
    def get_extraction_recommendation(info):
        """
        获取推荐选中的字幕
        """
        return subtitle_extractor.SubtitleExtractor.get_default_selection(info)

    @staticmethod
    def extract_subtitles_stream(filepath, selected_subs, total_duration=0):
        """
        提取字幕 (生成器)
        """
        for msg in subtitle_extractor.SubtitleExtractor.extract_subtitles_v2(filepath, selected_subs, total_duration=total_duration):
            yield msg

    @staticmethod
    def convert_fps(paths, src_fps, dst_fps):
        """
        转换字幕帧率
        :param paths: 文件路径列表或目录路径
        :param src_fps: 源帧率
        :param dst_fps: 目标帧率
        :return: Generator yielding result messages
        """
        if isinstance(paths, str):
            if os.path.isdir(paths):
                paths = [paths]
            else:
                paths = [paths]
                
        dirs = set()
        files = []
        for p in paths:
            if os.path.isdir(p):
                dirs.add(p)
            elif os.path.isfile(p):
                files.append(p)
                
        for d in dirs:
            for root, _, filenames in os.walk(d):
                for f in filenames:
                    if f.lower().endswith(('.srt', '.ass')):
                        full_path = os.path.join(root, f)
                        success, msg = fps_converter.process_file(full_path, src_fps, dst_fps)
                        yield msg
                        
        for f in files:
            success, msg = fps_converter.process_file(f, src_fps, dst_fps)
            yield msg
