import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import os
import threading
import sys

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



import json

try:
    from version import __version__
except ImportError:
    __version__ = "0.0.0"

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
            "merge_output_suffix": ".zh&en.ass"
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
        self.setup_clean_frame()
        self.setup_merge_frame()
        self.setup_rename_frame()

        self.setup_extract_frame()
        self.setup_fps_frame()
        
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

    # --- Setup Frames ---

    def setup_clean_frame(self):
        frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.frames["clean"] = frame
        
        label = ctk.CTkLabel(frame, text="清理与格式化 (SRT/ASS)", font=self.font_title)
        label.pack(pady=10, anchor="w")

        # 选项
        self.clean_skip_merge_var = ctk.BooleanVar(value=False)

        # 统一网格区域 (按钮 + 拖拽)
        grid_container = ctk.CTkFrame(frame, fg_color="transparent")
        grid_container.pack(pady=10, fill="both", expand=True)

        grid_container.grid_columnconfigure(0, weight=1)
        grid_container.grid_columnconfigure(1, weight=1)
        grid_container.grid_columnconfigure(2, weight=1)
        grid_container.grid_rowconfigure(1, weight=1)

        # 按钮 (Row 0)
        ctk.CTkButton(grid_container, text="选择文件/文件夹 (清理SRT)", font=self.font_normal, command=lambda: self.run_task(self.task_clean_srt)).grid(row=0, column=0, padx=5, pady=(0, 10), sticky="ew")
        ctk.CTkButton(grid_container, text="选择文件/文件夹 (中文标点清理)", font=self.font_normal, command=lambda: self.run_task(self.task_format_chs)).grid(row=0, column=1, padx=5, pady=(0, 10), sticky="ew")
        ctk.CTkButton(grid_container, text="选择文件/文件夹 (缩放ASS描边)", font=self.font_normal, command=lambda: self.run_task(self.task_scale_ass)).grid(row=0, column=2, padx=5, pady=(0, 10), sticky="ew")

        # 1. 清理 SRT Config + DND (Row 1, Column 0)
        # 使用 sub-frame 包含 Checkbox 和 DND，实现高度压缩和底部对齐
        col0_frame = ctk.CTkFrame(grid_container, fg_color="transparent")
        col0_frame.grid(row=1, column=0, padx=5, sticky="nsew")
        col0_frame.grid_rowconfigure(1, weight=1) # DND expands
        col0_frame.grid_columnconfigure(0, weight=1)
        
        # Checkbox at top of Col 0
        chk = ctk.CTkCheckBox(col0_frame, text="跳过合并短字幕", variable=self.clean_skip_merge_var, font=self.font_normal)
        chk.grid(row=0, column=0, pady=(0, 5), sticky="w")
        
        # DND Frame at bottom of Col 0
        self.dnd_clean = ctk.CTkFrame(col0_frame, border_width=2, border_color="gray")
        self.dnd_clean.grid(row=1, column=0, sticky="nsew")
        
        lbl_clean = ctk.CTkLabel(self.dnd_clean, text="拖拽到此\n仅清理 SRT\n(带移除内容统计)", font=self.font_normal, text_color="gray")
        lbl_clean.place(relx=0.5, rely=0.5, anchor="center")

        # 2. 格式化中文 DND (Row 1)
        self.dnd_format = ctk.CTkFrame(grid_container, border_width=2, border_color="gray")
        self.dnd_format.grid(row=1, column=1, padx=5, sticky="nsew")
        
        lbl_format = ctk.CTkLabel(self.dnd_format, text="拖拽到此\n格式化中文 SRT\n(标点处理)", font=self.font_normal, text_color="gray")
        lbl_format.place(relx=0.5, rely=0.5, anchor="center")

        # 3. ASS 缩放 DND (Row 1)
        self.dnd_ass = ctk.CTkFrame(grid_container, border_width=2, border_color="gray")
        self.dnd_ass.grid(row=1, column=2, padx=5, sticky="nsew")
        
        lbl_ass = ctk.CTkLabel(self.dnd_ass, text="拖拽到此\nASS 描边缩放\n(1080p优化)", font=self.font_normal, text_color="gray")
        lbl_ass.place(relx=0.5, rely=0.5, anchor="center")
        
        if HAS_DND:
            for widget in [self.dnd_clean, self.dnd_format, self.dnd_ass]:
                widget.drop_target_register(DND_FILES)
            
            self.dnd_clean.dnd_bind('<<Drop>>', self.on_drop_clean_only)
            self.dnd_format.dnd_bind('<<Drop>>', self.on_drop_format_only)
            self.dnd_ass.dnd_bind('<<Drop>>', self.on_drop_ass_only)


    def setup_merge_frame(self):
        frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.frames["merge"] = frame
        
        # 顶部布局分两列
        top_frame = ctk.CTkFrame(frame, fg_color="transparent")
        top_frame.pack(fill="x", pady=10)
        
        left_col = ctk.CTkFrame(top_frame, fg_color="transparent")
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 10))
        
        right_col = ctk.CTkFrame(top_frame, fg_color="transparent")
        right_col.pack(side="right", fill="both", expand=True)

        label = ctk.CTkLabel(left_col, text="合并双语字幕 (SRT -> ASS)", font=self.font_title)
        label.pack(pady=10, anchor="w")
        
        info = ctk.CTkLabel(left_col, text="说明: 要求文件夹内同时存在原语言和翻译语言文件。\n默认为 .srt 和 .zh.srt。\n也可直接拖拽配对的源语言 .srt 文件。", font=self.font_normal, justify="left")
        info.pack(pady=5, anchor="w")

        ctk.CTkButton(left_col, text="选择文件夹合并", font=self.font_normal, command=lambda: self.run_task(self.task_merge_bilingual)).pack(pady=20, anchor="w")
        
        # 右侧配置项
        def add_config_row(parent, text, key):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=text, width=120, anchor="w", font=self.font_normal).pack(side="left")
            var = ctk.StringVar(value=self.config.get(key, ""))
            def on_change(*args):
                self.config[key] = var.get()
                self.save_config()
            var.trace_add("write", on_change)
            entry = ctk.CTkEntry(row, textvariable=var, font=self.font_normal)
            entry.pack(side="left", fill="x", expand=True)
            return var

        ctk.CTkLabel(right_col, text="自定义设置", font=self.font_bold).pack(pady=(0, 5), anchor="w")
        self.var_merge_suffix = add_config_row(right_col, "翻译文件后缀:", "merge_translated_suffix")
        self.var_merge_out_suffix = add_config_row(right_col, "合并后后缀:", "merge_output_suffix")
        self.var_merge_l1_name = add_config_row(right_col, "翻译样式名:", "merge_lang1_style_name")
        self.var_merge_l1_def = add_config_row(right_col, "翻译样式定义:", "merge_lang1_style_def")
        self.var_merge_l2_name = add_config_row(right_col, "原始样式名:", "merge_lang2_style_name")
        self.var_merge_l2_def = add_config_row(right_col, "原始样式定义:", "merge_lang2_style_def")
        self.var_merge_author = add_config_row(right_col, "作者 (Author):", "merge_author")
        self.var_merge_comment = add_config_row(right_col, "注释 (Comment):", "merge_comment")
        
        # 拖拽区域

        dnd_frame = ctk.CTkFrame(frame, border_width=2, border_color="gray")
        dnd_frame.pack(pady=20, fill="both", expand=True)
        dnd_label = ctk.CTkLabel(dnd_frame, text="拖拽文件夹或文件到此处", font=self.font_normal, text_color="gray")
        dnd_label.place(relx=0.5, rely=0.5, anchor="center")

        if HAS_DND:
            dnd_frame.drop_target_register(DND_FILES)
            dnd_frame.dnd_bind('<<Drop>>', self.on_drop_merge)

    def setup_rename_frame(self):
        frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.frames["rename"] = frame
        
        label = ctk.CTkLabel(frame, text="批量重命名字幕", font=self.font_title)
        label.pack(pady=10, anchor="w")
        
        info = ctk.CTkLabel(frame, text="说明: 根据视频文件名 (SxxExx) 重命名对应的字幕文件。\n支持拖拽文件夹或视频+字幕文件。", font=self.font_normal, justify="left")
        info.pack(pady=5, anchor="w")
        
        ctk.CTkButton(frame, text="选择文件夹重命名", font=self.font_normal, command=lambda: self.run_task(self.task_rename_subs)).pack(pady=20, anchor="w")

        # 拖拽区域
        dnd_frame = ctk.CTkFrame(frame, border_width=2, border_color="gray")
        dnd_frame.pack(pady=20, fill="both", expand=True)
        dnd_label = ctk.CTkLabel(dnd_frame, text="拖拽文件夹或文件到此处", font=self.font_normal, text_color="gray")
        dnd_label.place(relx=0.5, rely=0.5, anchor="center")

        if HAS_DND:
            dnd_frame.drop_target_register(DND_FILES)
            dnd_frame.dnd_bind('<<Drop>>', self.on_drop_rename)


    def setup_extract_frame(self):
        frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.frames["extract"] = frame
        
        # 使用 Grid 布局以确保底部按钮可见性
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(4, weight=1) # Row 4 (Scroll) expands

        # Row 0: Title
        label = ctk.CTkLabel(frame, text="字幕提取 (FFmpeg)", font=self.font_title)
        label.grid(row=0, column=0, sticky="w", padx=10, pady=10)
        
        # Row 1: File Selection
        self.extract_file_var = ctk.StringVar(value="未选择文件")
        
        file_frame = ctk.CTkFrame(frame, fg_color="transparent")
        file_frame.grid(row=1, column=0, sticky="ew", padx=0, pady=5)
        
        ctk.CTkButton(file_frame, text="选择视频文件", font=self.font_normal, command=self.select_video_file).pack(side="left", padx=(10, 10))
        self.lbl_extract_file = ctk.CTkLabel(file_frame, textvariable=self.extract_file_var, font=self.font_normal, text_color="gray", anchor="w")
        self.lbl_extract_file.pack(side="left", fill="x", expand=True)

        # Row 2: DnD
        if HAS_DND:
            dnd_frame = ctk.CTkFrame(frame, border_width=2, border_color="gray", height=60)
            dnd_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=10)
            dnd_frame.pack_propagate(False) 
            
            dnd_label = ctk.CTkLabel(dnd_frame, text="拖拽视频文件到此处 (MP4 / MKV)", font=self.font_normal, text_color="gray")
            dnd_label.place(relx=0.5, rely=0.5, anchor="center")
            
            dnd_frame.drop_target_register(DND_FILES)
            dnd_frame.dnd_bind('<<Drop>>', self.on_drop_extract)

        # Row 3: Track Label
        ctk.CTkLabel(frame, text="可用字幕轨道:", font=self.font_bold).grid(row=3, column=0, sticky="w", padx=10, pady=(10, 5))
        
        # Row 4: Scroll List (Expands)
        self.tracks_scroll = ctk.CTkScrollableFrame(frame, height=100)
        self.tracks_scroll.grid(row=4, column=0, sticky="nsew", padx=10, pady=5)
        
        # Row 5: Button (Fixed at bottom)
        ctk.CTkButton(frame, text="开始提取选中字幕", font=self.font_large_bold, height=40, command=lambda: self.run_task(self.task_dev_extract)).grid(row=5, column=0, sticky="ew", padx=10, pady=10)

        # 内部变量
        self.current_video_path = None
        self.current_video_info = None
        self.track_vars = [] # list of (dict_info, BooleanVar)

    def setup_fps_frame(self):
        frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.frames["fps"] = frame
        
        label = ctk.CTkLabel(frame, text="帧率转换 (SRT/ASS)", font=self.font_title)
        label.pack(pady=10, anchor="w")
        
        info = ctk.CTkLabel(frame, text="说明: 对包含时间轴的字幕进行帧率转换。源文件将被备份为 .bak。", font=self.font_normal, justify="left")
        info.pack(pady=5, anchor="w")

        fps_options = ["23.976", "24", "25", "29.97", "30", "59.94", "60"]
        self.src_fps_var = ctk.StringVar(value="23.976")
        self.dst_fps_var = ctk.StringVar(value="25")

        options_frame = ctk.CTkFrame(frame, fg_color="transparent")
        options_frame.pack(pady=10, fill="x")

        ctk.CTkLabel(options_frame, text="源帧率:", font=self.font_normal).pack(side="left", padx=5)
        ctk.CTkComboBox(options_frame, values=fps_options, variable=self.src_fps_var, font=self.font_normal, width=120).pack(side="left", padx=5)

        ctk.CTkLabel(options_frame, text="->", font=self.font_normal).pack(side="left", padx=10)

        ctk.CTkLabel(options_frame, text="目标帧率:", font=self.font_normal).pack(side="left", padx=5)
        ctk.CTkComboBox(options_frame, values=fps_options, variable=self.dst_fps_var, font=self.font_normal, width=120).pack(side="left", padx=5)

        ctk.CTkButton(frame, text="选择文件/文件夹转换", font=self.font_normal, command=lambda: self.run_task(self.task_convert_fps)).pack(pady=20, anchor="w")

        # 拖拽区域
        dnd_frame = ctk.CTkFrame(frame, border_width=2, border_color="gray")
        dnd_frame.pack(pady=20, fill="both", expand=True)
        dnd_label = ctk.CTkLabel(dnd_frame, text="拖拽文件夹或文件到此处", font=self.font_normal, text_color="gray")
        dnd_label.place(relx=0.5, rely=0.5, anchor="center")

        if HAS_DND:
            dnd_frame.drop_target_register(DND_FILES)
            dnd_frame.dnd_bind('<<Drop>>', self.on_drop_fps)

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

    def on_drop_clean_only(self, event):
        files = self.parse_drop_files(event.data)
        if not files: return
        self.log(f"清理 SRT: {len(files)} 个文件/文件夹")
        self.run_task(lambda: self.task_clean_srt_run(files))

    def on_drop_format_only(self, event):
        files = self.parse_drop_files(event.data)
        if not files: return
        self.log(f"格式化中文: {len(files)} 个文件/文件夹")
        self.run_task(lambda: self.task_format_chs_run(files))

    def on_drop_ass_only(self, event):
        files = self.parse_drop_files(event.data)
        if not files: return
        self.log(f"ASS 缩放: {len(files)} 个文件/文件夹")
        self.run_task(lambda: self.task_scale_ass_run(files))

    def on_drop_assign(self, event, string_var):
        files = self.parse_drop_files(event.data)
        if files:
            string_var.set(files[0]) # 只取第一个

    def on_drop_merge(self, event):
        files = self.parse_drop_files(event.data)
        if not files: return
        self.run_task(lambda: self.task_merge_bilingual(files))

    def on_drop_rename(self, event):
        files = self.parse_drop_files(event.data)
        if not files: return
        self.run_task(lambda: self.task_rename_subs(files))

    def on_drop_fps(self, event):
        files = self.parse_drop_files(event.data)
        if not files: return
        self.run_task(lambda: self.task_convert_fps_run(files))

    def on_drop_extract(self, event):
        files = self.parse_drop_files(event.data)
        if not files: return
        # 只处理第一个文件
        f = files[0]
        if os.path.isfile(f):
            self.load_video_info(f)

    def select_video_file(self):
        f = filedialog.askopenfilename(filetypes=[("Video Files", "*.mp4 *.mkv *.avi *.mov"), ("All Files", "*.*")])
        if f:
            self.load_video_info(f)

    def load_video_info(self, filepath):
        self.current_video_path = filepath
        self.extract_file_var.set(os.path.basename(filepath))
        self.log(f"正在分析视频文件: {filepath} ...")
        
        # 清空列表
        for widget in self.tracks_scroll.winfo_children():
            widget.destroy()
        self.track_vars = []
        
        threading.Thread(target=self.task_analyze_video, args=(filepath,)).start()

    def task_analyze_video(self, filepath):
        if not SubtitleTool: 
             self.log("Error: Tools not loaded.")
             return
             
        info = SubtitleTool.get_video_info(filepath)
        if not info:
            self.log("无法获取媒体信息 (ffprobe 失败?)")
            return
            
        self.current_video_info = info
            
        if info.get("warnings"):
            for w in info["warnings"]:
                self.log(w)
            
        # Get defaults
        recommendations = SubtitleTool.get_extraction_recommendation(info)
        
        # Update UI in main thread? CTk is somewhat thread safe for setting vars but adding widgets should be careful.
        # usually best to use .after or specific update method. CTk widgets creation MUST be in main thread.
        self.after(0, lambda: self.render_track_list(info, recommendations))

    def render_track_list(self, info, recommendations):
        subs = info.get("subtitles", [])
        if not subs:
            ctk.CTkLabel(self.tracks_scroll, text="未找到字幕轨道", font=self.font_normal).pack(pady=10)
            self.log(f"分析完成: 无字幕轨道")
            return
            
        audio_info = f"Audio: {len(info.get('audio_langs', []))} tracks (Default: {info.get('default_audio_lang', 'None')})"
        self.log(f"分析完成: {len(subs)} 个字幕轨道. {audio_info}")
        
        for sub in subs:
            idx = sub['index']
            lang = sub['language']
            title = sub['title']
            codec = sub['codec_name']
            is_default = sub['default']
            is_forced = sub['forced']
            is_hi = sub['hearing_impaired']
            
            # Flags string
            flags = []
            if is_default: flags.append("Default")
            if is_forced: flags.append("Forced")
            if is_hi: flags.append("SDH")
            if sub['dub']: flags.append("Dub")
            
            flag_str = f"[{', '.join(flags)}]" if flags else ""
            display_text = f"Track {idx}: {lang} ({codec}) {flag_str} {title}"
            
            var = ctk.BooleanVar(value=(idx in recommendations))
            
            track_frame = ctk.CTkFrame(self.tracks_scroll, fg_color="transparent")
            track_frame.pack(anchor="w", fill="x", pady=2, padx=5)
            
            chk = ctk.CTkCheckBox(track_frame, text=display_text, variable=var, font=self.font_normal)
            chk.pack(side="left")
            
            vtt_var = None
            if codec and "webvtt" in codec.lower():
                vtt_var = ctk.BooleanVar(value=True)
                small_font = ctk.CTkFont(family="Microsoft YaHei", size=11)
                vtt_chk = ctk.CTkCheckBox(track_frame, text="转为SRT", variable=vtt_var, font=small_font, checkbox_width=16, checkbox_height=16, text_color_disabled="gray")
                vtt_chk.pack(side="left", padx=(10, 0))
                
                # 初始化状态
                if not var.get():
                    vtt_chk.configure(state="disabled", border_color="gray", fg_color="gray")
                    
                # 绑定事件关联状态
                def toggle_vtt_state(track_var=var, v_chk=vtt_chk):
                    if track_var.get():
                        v_chk.configure(state="normal", border_color=ctk.ThemeManager.theme["CTkCheckBox"]["border_color"], fg_color=ctk.ThemeManager.theme["CTkCheckBox"]["fg_color"])
                    else:
                        v_chk.configure(state="disabled", border_color="gray", fg_color="gray")
                
                chk.configure(command=toggle_vtt_state)
                
            self.track_vars.append((sub, var, vtt_var))

    def task_dev_extract(self):
        if not self.current_video_path:
            self.log("请先选择视频文件")
            return
            
        selected_subs = []
        for track_item in self.track_vars:
            if len(track_item) == 3:
                sub_info, var, vtt_var = track_item
            else:
                sub_info, var = track_item
                vtt_var = None
                
            if var.get():
                sub_copy = dict(sub_info)  # safe copy
                if vtt_var and vtt_var.get():
                    sub_copy["convert_vtt_to_srt"] = True
                selected_subs.append(sub_copy)
        
        if not selected_subs:
            self.log("未选择任何轨道")
            return
            
        self.log(f"开始提取 {len(selected_subs)} 个轨道...")
        self.log(f"开始提取 {len(selected_subs)} 个轨道...")
        
        total_duration = 0
        if self.current_video_info:
            total_duration = self.current_video_info.get("duration", 0)
            
        for msg in SubtitleTool.extract_subtitles_stream(self.current_video_path, selected_subs, total_duration=total_duration):
            if "提取进度" in msg:
                self.log_progress(msg)
            else:
                self.log(msg)
        self.log("提取任务结束")

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

    # --- Tasks ---

    def task_clean_srt(self):
        paths = self.get_paths()
        if not paths: return
        self.task_clean_srt_run(paths)

    def task_clean_srt_run(self, paths):
        self.log("开始清理 SRT...")
        for msg in SubtitleTool.clean_srt(paths, skip_merge=self.clean_skip_merge_var.get()):
            self.log(msg)
        self.log("任务结束")

    def task_format_chs(self):
        paths = self.get_paths()
        if not paths: return
        self.task_format_chs_run(paths)

    def task_format_chs_run(self, paths):
        self.log("开始格式化中文 SRT...")
        for msg in SubtitleTool.format_chs_srt(paths):
            self.log(msg)
        self.log("任务结束")

    def task_scale_ass(self):
        paths = self.get_paths()
        if not paths: return
        self.task_scale_ass_run(paths)

    def task_scale_ass_run(self, paths):
        self.log("开始处理 ASS 描边...")
        for msg in SubtitleTool.scale_ass_outline(paths):
            self.log(msg)
        self.log("任务结束")

    # Removed task_smart_process as it is replaced by explicit drag zones

    def task_merge_bilingual(self, paths=None):
        if not paths:
            paths = self.get_paths("folder")
            if not paths: return
            
        kwargs = {
            "translated_suffix": self.config.get("merge_translated_suffix", ".zh.srt"),
            "lang1_style_name": self.config.get("merge_lang1_style_name", "Translate"),
            "lang1_style_def": self.config.get("merge_lang1_style_def", "黑体, 60, &H00EEEEEE, &HF0000000, &H00000000, &H32000000, 0, 0, 0, 0, 100, 100, 0, 0, 1, 1.5, 0, 2, 18, 18, 18, 1"),
            "lang2_style_name": self.config.get("merge_lang2_style_name", "Original"),
            "lang2_style_def": self.config.get("merge_lang2_style_def", "Arial, 40, &H00EEEEEE, &HF0000000, &H00000000, &H32000000, 0, 0, 0, 0, 100, 100, 0, 0, 1, 1.5, 0, 2, 18, 18, 18, 1"),
            "author": self.config.get("merge_author", "default"),
            "comment": self.config.get("merge_comment", ""),
            "output_suffix": self.config.get("merge_output_suffix", ".zh&en.ass")
        }
            
        self.log(f"开始合并双语字幕: {len(paths)} 个项目")
        for msg in SubtitleTool.merge_bilingual_srt(paths, **kwargs):
            self.log(msg)
        self.log("任务结束")

    def task_rename_subs(self, paths=None):
        if not paths:
             paths = self.get_paths("folder")
             if not paths: return
             
        self.log(f"开始重命名字幕: {len(paths)} 个项目")
        for msg in SubtitleTool.rename_subtitles(paths):
            self.log(msg)
        self.log("任务结束")

    def task_convert_fps(self):
        paths = self.get_paths()
        if not paths: return
        self.task_convert_fps_run(paths)

    def task_convert_fps_run(self, paths):
        src_fps_val = self.src_fps_var.get().strip()
        dst_fps_val = self.dst_fps_var.get().strip()
        
        if not src_fps_val or not dst_fps_val:
            self.log("帧率不能为空")
            return
            
        self.log(f"开始转换帧率: {len(paths)} 个项目 ({src_fps_val} -> {dst_fps_val})")
        for msg in SubtitleTool.convert_fps(paths, src_fps_val, dst_fps_val):
            self.log(msg)
        self.log("任务结束")



if __name__ == "__main__":
    app = App()
    app.mainloop()
