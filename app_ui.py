import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import os
import threading
import sys
import json

# 尝试导入 backend tools
# 将 tools 目录加入 path 以便导入
current_dir = os.path.dirname(os.path.abspath(__file__))
tools_dir = os.path.join(current_dir, 'tools')
if tools_dir not in sys.path:
    sys.path.append(tools_dir)

try:
    from tools.subtitle_api import SubtitleTool
except ImportError:
    # 尝试直接导入（如果在 tools 目录下运行）
    try:
        from subtitle_api import SubtitleTool
    except ImportError as e:
        print(f"Error importing tools: {e}")
        SubtitleTool = None

# 尝试导入 TkinterDnD 用于拖拽
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
    class CTk(ctk.CTk, TkinterDnD.DnDWrapper):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.TkdndVersion = TkinterDnD._require(self)
except ImportError:
    HAS_DND = False
    class CTk(ctk.CTk):
        pass

ctk.set_appearance_mode("System")  # Modes: "System" (standard), "Dark", "Light"
ctk.set_default_color_theme("blue")  # Themes: "blue" (standard), "green", "dark-blue"

# 设置默认字体为各类中文字体支持较好的微软雅黑，解决日文字形问题
# 注意：CustomTkinter 的 Theme JSON 也可以配置，但代码中全局设置比较直接
# ctk.CTkFont 默认系列
DEFAULT_FONT = ("Microsoft YaHei", 12)

try:
    from version import __version__
except ImportError:
    __version__ = "0.0.0"

from ui.clean_frame import CleanFrame
from ui.merge_frame import MergeFrame
from ui.rename_frame import RenameFrame
from ui.extract_frame import ExtractFrame
from ui.fps_frame import FpsFrame

class App(CTk):
    CONFIG_FILE = "config.json"
    
    def load_config(self):
        default_config = {
            "merge_translated_suffix": ".zh.srt",
            "merge_lang1_style_name": "Translate",
            "merge_lang1_style_def": "黑体, 60, &H00EEEEEE, &HF0000000, &H00000000, &H32000000, 0, 0, 0, 0, 100, 100, 0, 0, 1, 1.5, 0, 2, 18, 18, 18, 1",
            "merge_lang2_style_name": "Original",
            "merge_lang2_style_def": "Arial, 40, &H00EEEEEE, &HF0000000, &H00000000, &H32000000, 0, 0, 0, 0, 100, 100, 0, 0, 1, 1.5, 0, 2, 18, 18, 18, 1",
            "merge_author": "default",
            "merge_comment": "",
            "merge_output_suffix": ".zh&en.ass",
            "merge_playresx": 1920,
            "merge_playresy": 1080
        }
        if os.path.exists(self.CONFIG_FILE):
            try:
                with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
                    default_config.update(user_config)
            except Exception as e:
                print(f"Failed to load config: {e}")
        return default_config

    def save_config(self):
        try:
            with open(self.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Failed to save config: {e}")

    def __init__(self):
        super().__init__()
        
        self.config = self.load_config()
        
        # 预先定义字体 helper
        self.font_normal = ctk.CTkFont(family="Microsoft YaHei", size=12)
        self.font_bold = ctk.CTkFont(family="Microsoft YaHei", size=12, weight="bold")
        self.font_large_bold = ctk.CTkFont(family="Microsoft YaHei", size=20, weight="bold")
        self.font_title = ctk.CTkFont(family="Microsoft YaHei", size=18, weight="bold")

        self.title(f"Subtitle Tools / 字幕工具箱 v{__version__}")
        self.geometry("800x600")

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # 左侧导航栏
        self.sidebar_frame = ctk.CTkFrame(self, width=140, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, rowspan=4, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(7, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="字幕工具箱", font=self.font_large_bold)
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        self.sidebar_button_clean = ctk.CTkButton(self.sidebar_frame, text="清理格式化", font=self.font_normal, command=lambda: self.select_frame("clean"))
        self.sidebar_button_clean.grid(row=1, column=0, padx=20, pady=10)

        self.sidebar_button_merge = ctk.CTkButton(self.sidebar_frame, text="合并双语", font=self.font_normal, command=lambda: self.select_frame("merge"))
        self.sidebar_button_merge.grid(row=2, column=0, padx=20, pady=10)
        
        self.sidebar_button_rename = ctk.CTkButton(self.sidebar_frame, text="重命名字幕", font=self.font_normal, command=lambda: self.select_frame("rename"))
        self.sidebar_button_rename.grid(row=3, column=0, padx=20, pady=10)

        self.sidebar_button_extract = ctk.CTkButton(self.sidebar_frame, text="字幕提取", font=self.font_normal, command=lambda: self.select_frame("extract"))
        self.sidebar_button_extract.grid(row=5, column=0, padx=20, pady=10)

        self.sidebar_button_fps = ctk.CTkButton(self.sidebar_frame, text="帧率转换", font=self.font_normal, command=lambda: self.select_frame("fps"))
        self.sidebar_button_fps.grid(row=6, column=0, padx=20, pady=10)

        self.appearance_mode_label = ctk.CTkLabel(self.sidebar_frame, text="外观模式:", font=self.font_normal, anchor="w")
        self.appearance_mode_label.grid(row=8, column=0, padx=20, pady=(10, 0))
        self.appearance_mode_optionemenu = ctk.CTkOptionMenu(self.sidebar_frame, values=["System", "Light", "Dark"],
                                                                       font=self.font_normal,
                                                                       command=self.change_appearance_mode_event)
        self.appearance_mode_optionemenu.grid(row=9, column=0, padx=20, pady=(10, 20))
        
        # 主功能区
        self.frames = {}
        self.frames["clean"] = CleanFrame(self, app=self, corner_radius=0, fg_color="transparent")
        self.frames["merge"] = MergeFrame(self, app=self, corner_radius=0, fg_color="transparent")
        self.frames["rename"] = RenameFrame(self, app=self, corner_radius=0, fg_color="transparent")
        self.frames["extract"] = ExtractFrame(self, app=self, corner_radius=0, fg_color="transparent")
        self.frames["fps"] = FpsFrame(self, app=self, corner_radius=0, fg_color="transparent")
        
        # 底部日志区
        self.log_frame = ctk.CTkFrame(self, corner_radius=0, height=100)
        self.log_frame.grid(row=1, column=1, sticky="nsew", padx=10, pady=10)
        self.log_frame.grid_rowconfigure(0, weight=1)
        self.log_frame.grid_columnconfigure(0, weight=1)
        
        self.log_box = ctk.CTkTextbox(self.log_frame, font=self.font_normal, height=100)
        self.log_box.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.last_log_was_progress = False
        self.log("程序已启动...")
        if not HAS_DND:
            self.log("提示: 未检测到 tkinterdnd2，拖拽功能不可用。")
        else:
             self.log("提示: 支持文件拖拽。")

        self.select_frame("clean")

    def log(self, message):
        self.last_log_was_progress = False
        self.log_box.insert("end", str(message) + "\n")
        self.log_box.see("end")

    def log_progress(self, message):
        if self.last_log_was_progress:
            # Delete the previous progress line (which is the last line before 'end')
            # 'end-1l' to 'end' covers the last line including the newline
            self.log_box.delete("end-2l", "end-1l") 
        
        self.log_box.insert("end", str(message) + "\n")
        self.log_box.see("end")
        self.last_log_was_progress = True

    def change_appearance_mode_event(self, new_appearance_mode: str):
        ctk.set_appearance_mode(new_appearance_mode)

    def select_frame(self, name):
        # 隐藏所有 frame
        for frame in self.frames.values():
            frame.grid_forget()
        # 显示选中的 frame
        if name in self.frames:
            self.frames[name].grid(row=0, column=1, sticky="nsew", padx=10, pady=10)

    # --- Helpers ---

    def select_file(self, var):
        path = filedialog.askopenfilename()
        if path:
            var.set(path)

    def get_paths(self, kind="any"):
        # 弹窗询问选择文件还是文件夹 (Tkinter没有混合选择)
        # 这里简化：如果kind是folder则只选folder，否则选文件
        if kind == "folder":
            p = filedialog.askdirectory()
            return [p] if p else []
        else:
             p = filedialog.askopenfilenames()
             return list(p) if p else []

    def parse_drop_files(self, data):
        if not data:
            return []
            
        import re
        # tkinterdnd2/Tcl list parsing:
        # Regex matches: {path with spaces} OR non_space_path
        # Note: This handles "{A} {B}", "A B", "{A} B", etc.
        matches = re.findall(r'\{(.+?)\}|(\S+)', data)
        return [m[0] if m[0] else m[1] for m in matches]

    def run_task(self, task_func):
        threading.Thread(target=task_func).start()


if __name__ == "__main__":
    app = App()
    app.mainloop()
