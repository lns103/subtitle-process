import os
import sys
import ctypes

def normalize_path(path: str) -> str:
    """
    规范化路径：
    1. 在 Windows 系统下，如果路径为 8.3 短路径 (如包含 NOONEW~1.265)，
       调用 ctypes Kernel32.GetLongPathNameW 自动还原为完整长路径。
    2. 返回规范化的绝对路径。
    """
    if not path or not isinstance(path, str):
        return path
    
    # 清除首尾可能的双引号或空白
    clean_p = path.strip(' \t\r\n"')
    if not clean_p:
        return path

    abs_p = os.path.abspath(clean_p)

    if sys.platform == "win32":
        try:
            buffer = ctypes.create_unicode_buffer(1024)
            result = ctypes.windll.kernel32.GetLongPathNameW(abs_p, buffer, 1024)
            if result > 0 and result <= 1024:
                return buffer.value
        except Exception:
            pass

    return abs_p

def normalize_paths(paths) -> list[str]:
    """
    批量规范化路径列表
    """
    if not paths:
        return []
    if isinstance(paths, str):
        paths = [paths]
    
    result = []
    for p in paths:
        norm_p = normalize_path(p)
        if norm_p and norm_p not in result:
            result.append(norm_p)
    return result

def get_safe_open_path(path: str) -> str:
    """
    针对 Windows 下超长路径（> 240 字符）自动添加 Extended-Length 前缀 \\?\\
    """
    norm_p = normalize_path(path)
    if sys.platform == "win32" and len(norm_p) > 240 and not norm_p.startswith("\\\\?\\"):
        if norm_p.startswith("\\\\"):
            # UNC path
            return "\\\\?\\UNC\\" + norm_p[2:]
        else:
            return "\\\\?\\" + norm_p
    return norm_p
