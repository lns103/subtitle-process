import customtkinter as ctk
import threading
from tools.subtitle_api import SubtitleTool

try:
    from tkinterdnd2 import DND_FILES
    HAS_DND = True
except ImportError:
    HAS_DND = False

class ShiftFrame(ctk.CTkFrame):
    def __init__(self, master, app, **kwargs):
        super().__init__(master, **kwargs)
        self.app = app
        
        label = ctk.CTkLabel(self, text="时间轴平移 (SRT/ASS)", font=self.app.font_title)
        label.pack(padx=5, pady=(10, 10), anchor="w")
        
        info = ctk.CTkLabel(self, text="说明: 对字幕文件进行时间轴整体平移。正数延后，负数提前（秒）。源文件将被备份为 .bak。", font=self.app.font_normal, justify="left")
        info.pack(padx=5, pady=(0, 10), anchor="w")

        self.offset_var = ctk.StringVar(value="0.0")

        options_frame = ctk.CTkFrame(self, fg_color="transparent")
        options_frame.pack(padx=5, pady=(0, 10), fill="x")

        ctk.CTkLabel(options_frame, text="时间偏移量(秒):", font=self.app.font_normal).pack(side="left", padx=5)
        ctk.CTkEntry(options_frame, textvariable=self.offset_var, font=self.app.font_normal, width=120).pack(side="left", padx=5)
        
        ctk.CTkLabel(options_frame, text="例如: 1.5 表示延后1.5秒, -2 表示提前2秒", font=self.app.font_normal, text_color="gray").pack(side="left", padx=10)

        ctk.CTkButton(self, text="选择文件/文件夹处理", font=self.app.font_normal, command=self.task_shift_time).pack(padx=5, pady=(10, 10), anchor="w")

        # 拖拽区域
        dnd_frame = ctk.CTkFrame(self, border_width=2, border_color="gray")
        dnd_frame.pack(padx=5, pady=(10, 10), fill="both", expand=True)
        dnd_label = ctk.CTkLabel(dnd_frame, text="拖拽文件夹或文件到此处", font=self.app.font_normal, text_color="gray")
        dnd_label.place(relx=0.5, rely=0.5, anchor="center")

        if HAS_DND:
            dnd_frame.drop_target_register(DND_FILES)
            dnd_frame.dnd_bind('<<Drop>>', self.on_drop_shift)

    def on_drop_shift(self, event):
        files = self.app.parse_drop_files(event.data)
        if not files: return
        self.app.run_task(lambda: self.task_shift_time_run(files))

    def task_shift_time(self):
        paths = self.app.get_paths()
        if not paths: return
        self.app.run_task(lambda: self.task_shift_time_run(paths))

    def task_shift_time_run(self, paths):
        offset_val = self.offset_var.get().strip()
        
        if not offset_val:
            self.app.log("时间偏移量不能为空")
            return
            
        try:
            float(offset_val)
        except ValueError:
            self.app.log(f"无效的时间偏移量: {offset_val}")
            return
            
        self.app.log(f"开始平移时间轴: {len(paths)} 个项目 (偏移: {offset_val} 秒)")
        if SubtitleTool is None:
            self.app.log("Error: SubtitleTool not loaded.")
            return

        for msg in SubtitleTool.shift_time(paths, offset_val):
            self.app.log(msg)
        self.app.log("任务结束")
