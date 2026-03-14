import customtkinter as ctk
import threading
from tools.subtitle_api import SubtitleTool

try:
    from tkinterdnd2 import DND_FILES
    HAS_DND = True
except ImportError:
    HAS_DND = False

class RenameFrame(ctk.CTkFrame):
    def __init__(self, master, app, **kwargs):
        super().__init__(master, **kwargs)
        self.app = app
        
        label = ctk.CTkLabel(self, text="批量重命名字幕", font=self.app.font_title)
        label.pack(pady=10, anchor="w")
        
        info = ctk.CTkLabel(self, text="说明: 根据视频文件名 (SxxExx) 重命名对应的字幕文件。\n支持拖拽文件夹或视频+字幕文件。", font=self.app.font_normal, justify="left")
        info.pack(pady=5, anchor="w")
        
        ctk.CTkButton(self, text="选择文件夹重命名", font=self.app.font_normal, command=self.task_rename_subs).pack(pady=20, anchor="w")

        # 拖拽区域
        dnd_frame = ctk.CTkFrame(self, border_width=2, border_color="gray")
        dnd_frame.pack(pady=20, fill="both", expand=True)
        dnd_label = ctk.CTkLabel(dnd_frame, text="拖拽文件夹或文件到此处", font=self.app.font_normal, text_color="gray")
        dnd_label.place(relx=0.5, rely=0.5, anchor="center")

        if HAS_DND:
            dnd_frame.drop_target_register(DND_FILES)
            dnd_frame.dnd_bind('<<Drop>>', self.on_drop_rename)

    def on_drop_rename(self, event):
        files = self.app.parse_drop_files(event.data)
        if not files: return
        self.app.run_task(lambda: self.task_rename_subs_run(files))

    def task_rename_subs(self):
        paths = self.app.get_paths("folder")
        if not paths: return
        self.app.run_task(lambda: self.task_rename_subs_run(paths))

    def task_rename_subs_run(self, paths):
        if SubtitleTool is None:
            self.app.log("Error: SubtitleTool not loaded.")
            return

        self.app.log(f"开始重命名字幕: {len(paths)} 个项目")
        for msg in SubtitleTool.rename_subtitles(paths):
            self.app.log(msg)
        self.app.log("任务结束")
