import customtkinter as ctk
import threading
from tools.subtitle_api import SubtitleTool

try:
    from tkinterdnd2 import DND_FILES
    HAS_DND = True
except ImportError:
    HAS_DND = False

class CleanFrame(ctk.CTkFrame):
    def __init__(self, master, app, **kwargs):
        super().__init__(master, **kwargs)
        self.app = app
        
        label = ctk.CTkLabel(self, text="清理与格式化 (SRT/ASS)", font=self.app.font_title)
        label.pack(pady=10, anchor="w")

        # 选项
        self.clean_skip_merge_var = ctk.BooleanVar(value=False)

        # 统一网格区域 (按钮 + 拖拽)
        grid_container = ctk.CTkFrame(self, fg_color="transparent")
        grid_container.pack(pady=10, fill="both", expand=True)

        grid_container.grid_columnconfigure(0, weight=1)
        grid_container.grid_columnconfigure(1, weight=1)
        grid_container.grid_columnconfigure(2, weight=1)
        grid_container.grid_rowconfigure(1, weight=1)

        # 按钮 (Row 0)
        ctk.CTkButton(grid_container, text="选择文件/文件夹 (清理SRT)", font=self.app.font_normal, command=self.task_clean_srt).grid(row=0, column=0, padx=5, pady=(0, 10), sticky="ew")
        ctk.CTkButton(grid_container, text="选择文件/文件夹 (中文标点清理)", font=self.app.font_normal, command=self.task_format_chs).grid(row=0, column=1, padx=5, pady=(0, 10), sticky="ew")
        ctk.CTkButton(grid_container, text="选择文件/文件夹 (缩放ASS描边)", font=self.app.font_normal, command=self.task_scale_ass).grid(row=0, column=2, padx=5, pady=(0, 10), sticky="ew")

        # 1. 清理 SRT Config + DND (Row 1, Column 0)
        col0_frame = ctk.CTkFrame(grid_container, fg_color="transparent")
        col0_frame.grid(row=1, column=0, padx=5, sticky="nsew")
        col0_frame.grid_rowconfigure(1, weight=1) # DND expands
        col0_frame.grid_columnconfigure(0, weight=1)
        
        chk = ctk.CTkCheckBox(col0_frame, text="跳过合并短字幕", variable=self.clean_skip_merge_var, font=self.app.font_normal)
        chk.grid(row=0, column=0, pady=(0, 5), sticky="w")
        
        self.dnd_clean = ctk.CTkFrame(col0_frame, border_width=2, border_color="gray")
        self.dnd_clean.grid(row=1, column=0, sticky="nsew")
        
        lbl_clean = ctk.CTkLabel(self.dnd_clean, text="拖拽到此\n仅清理 SRT\n(带移除内容统计)", font=self.app.font_normal, text_color="gray")
        lbl_clean.place(relx=0.5, rely=0.5, anchor="center")

        # 2. 格式化中文 DND (Row 1)
        self.dnd_format = ctk.CTkFrame(grid_container, border_width=2, border_color="gray")
        self.dnd_format.grid(row=1, column=1, padx=5, sticky="nsew")
        
        lbl_format = ctk.CTkLabel(self.dnd_format, text="拖拽到此\n格式化中文 SRT\n(标点处理)", font=self.app.font_normal, text_color="gray")
        lbl_format.place(relx=0.5, rely=0.5, anchor="center")

        # 3. ASS 缩放 DND (Row 1)
        self.dnd_ass = ctk.CTkFrame(grid_container, border_width=2, border_color="gray")
        self.dnd_ass.grid(row=1, column=2, padx=5, sticky="nsew")
        
        lbl_ass = ctk.CTkLabel(self.dnd_ass, text="拖拽到此\nASS 描边缩放\n(1080p优化)", font=self.app.font_normal, text_color="gray")
        lbl_ass.place(relx=0.5, rely=0.5, anchor="center")
        
        if HAS_DND:
            for widget in [self.dnd_clean, self.dnd_format, self.dnd_ass]:
                widget.drop_target_register(DND_FILES)
            
            self.dnd_clean.dnd_bind('<<Drop>>', self.on_drop_clean_only)
            self.dnd_format.dnd_bind('<<Drop>>', self.on_drop_format_only)
            self.dnd_ass.dnd_bind('<<Drop>>', self.on_drop_ass_only)

    def on_drop_clean_only(self, event):
        files = self.app.parse_drop_files(event.data)
        if not files: return
        self.app.log(f"清理 SRT: {len(files)} 个文件/文件夹")
        self.app.run_task(lambda: self.task_clean_srt_run(files))

    def on_drop_format_only(self, event):
        files = self.app.parse_drop_files(event.data)
        if not files: return
        self.app.log(f"格式化中文: {len(files)} 个文件/文件夹")
        self.app.run_task(lambda: self.task_format_chs_run(files))

    def on_drop_ass_only(self, event):
        files = self.app.parse_drop_files(event.data)
        if not files: return
        self.app.log(f"ASS 缩放: {len(files)} 个文件/文件夹")
        self.app.run_task(lambda: self.task_scale_ass_run(files))

    def task_clean_srt(self):
        paths = self.app.get_paths()
        if not paths: return
        self.app.run_task(lambda: self.task_clean_srt_run(paths))

    def task_clean_srt_run(self, paths):
        self.app.log("开始清理 SRT...")
        if SubtitleTool is None:
            self.app.log("Error: SubtitleTool not loaded.")
            return
        for msg in SubtitleTool.clean_srt(paths, skip_merge=self.clean_skip_merge_var.get()):
            self.app.log(msg)
        self.app.log("任务结束")

    def task_format_chs(self):
        paths = self.app.get_paths()
        if not paths: return
        self.app.run_task(lambda: self.task_format_chs_run(paths))

    def task_format_chs_run(self, paths):
        self.app.log("开始格式化中文 SRT...")
        if SubtitleTool is None:
            self.app.log("Error: SubtitleTool not loaded.")
            return
        for msg in SubtitleTool.format_chs_srt(paths):
            self.app.log(msg)
        self.app.log("任务结束")

    def task_scale_ass(self):
        paths = self.app.get_paths()
        if not paths: return
        self.app.run_task(lambda: self.task_scale_ass_run(paths))

    def task_scale_ass_run(self, paths):
        self.app.log("开始处理 ASS 描边...")
        if SubtitleTool is None:
            self.app.log("Error: SubtitleTool not loaded.")
            return
        for msg in SubtitleTool.scale_ass_outline(paths):
            self.app.log(msg)
        self.app.log("任务结束")
