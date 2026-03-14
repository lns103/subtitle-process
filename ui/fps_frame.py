import customtkinter as ctk
import threading
from tools.subtitle_api import SubtitleTool

try:
    from tkinterdnd2 import DND_FILES
    HAS_DND = True
except ImportError:
    HAS_DND = False

class FpsFrame(ctk.CTkFrame):
    def __init__(self, master, app, **kwargs):
        super().__init__(master, **kwargs)
        self.app = app
        
        label = ctk.CTkLabel(self, text="帧率转换 (SRT/ASS)", font=self.app.font_title)
        label.pack(pady=10, anchor="w")
        
        info = ctk.CTkLabel(self, text="说明: 对包含时间轴的字幕进行帧率转换。源文件将被备份为 .bak。", font=self.app.font_normal, justify="left")
        info.pack(pady=5, anchor="w")

        fps_options = ["23.976", "24", "25", "29.97", "30", "59.94", "60"]
        self.src_fps_var = ctk.StringVar(value="23.976")
        self.dst_fps_var = ctk.StringVar(value="25")

        options_frame = ctk.CTkFrame(self, fg_color="transparent")
        options_frame.pack(pady=10, fill="x")

        ctk.CTkLabel(options_frame, text="源帧率:", font=self.app.font_normal).pack(side="left", padx=5)
        ctk.CTkComboBox(options_frame, values=fps_options, variable=self.src_fps_var, font=self.app.font_normal, width=120).pack(side="left", padx=5)

        ctk.CTkLabel(options_frame, text="->", font=self.app.font_normal).pack(side="left", padx=10)

        ctk.CTkLabel(options_frame, text="目标帧率:", font=self.app.font_normal).pack(side="left", padx=5)
        ctk.CTkComboBox(options_frame, values=fps_options, variable=self.dst_fps_var, font=self.app.font_normal, width=120).pack(side="left", padx=5)

        ctk.CTkButton(self, text="选择文件/文件夹转换", font=self.app.font_normal, command=self.task_convert_fps).pack(pady=20, anchor="w")

        # 拖拽区域
        dnd_frame = ctk.CTkFrame(self, border_width=2, border_color="gray")
        dnd_frame.pack(pady=20, fill="both", expand=True)
        dnd_label = ctk.CTkLabel(dnd_frame, text="拖拽文件夹或文件到此处", font=self.app.font_normal, text_color="gray")
        dnd_label.place(relx=0.5, rely=0.5, anchor="center")

        if HAS_DND:
            dnd_frame.drop_target_register(DND_FILES)
            dnd_frame.dnd_bind('<<Drop>>', self.on_drop_fps)

    def on_drop_fps(self, event):
        files = self.app.parse_drop_files(event.data)
        if not files: return
        self.app.run_task(lambda: self.task_convert_fps_run(files))

    def task_convert_fps(self):
        paths = self.app.get_paths()
        if not paths: return
        self.app.run_task(lambda: self.task_convert_fps_run(paths))

    def task_convert_fps_run(self, paths):
        src_fps_val = self.src_fps_var.get().strip()
        dst_fps_val = self.dst_fps_var.get().strip()
        
        if not src_fps_val or not dst_fps_val:
            self.app.log("帧率不能为空")
            return
            
        self.app.log(f"开始转换帧率: {len(paths)} 个项目 ({src_fps_val} -> {dst_fps_val})")
        if SubtitleTool is None:
            self.app.log("Error: SubtitleTool not loaded.")
            return

        for msg in SubtitleTool.convert_fps(paths, src_fps_val, dst_fps_val):
            self.app.log(msg)
        self.app.log("任务结束")
