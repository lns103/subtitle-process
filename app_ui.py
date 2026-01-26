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


class App(CTk):
    def __init__(self):
        super().__init__()
        
        # 预先定义字体 helper
        self.font_normal = ctk.CTkFont(family="Microsoft YaHei", size=12)
        self.font_bold = ctk.CTkFont(family="Microsoft YaHei", size=12, weight="bold")
        self.font_large_bold = ctk.CTkFont(family="Microsoft YaHei", size=20, weight="bold")
        self.font_title = ctk.CTkFont(family="Microsoft YaHei", size=18, weight="bold")


        self.title("Subtitle Tools / 字幕工具箱")
        self.geometry("800x600")

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # 左侧导航栏
        self.sidebar_frame = ctk.CTkFrame(self, width=140, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, rowspan=4, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(6, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="字幕工具箱", font=self.font_large_bold)
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        self.sidebar_button_clean = ctk.CTkButton(self.sidebar_frame, text="清理格式化", font=self.font_normal, command=lambda: self.select_frame("clean"))
        self.sidebar_button_clean.grid(row=1, column=0, padx=20, pady=10)

        self.sidebar_button_merge = ctk.CTkButton(self.sidebar_frame, text="合并双语", font=self.font_normal, command=lambda: self.select_frame("merge"))
        self.sidebar_button_merge.grid(row=2, column=0, padx=20, pady=10)
        
        self.sidebar_button_rename = ctk.CTkButton(self.sidebar_frame, text="重命名字幕", font=self.font_normal, command=lambda: self.select_frame("rename"))
        self.sidebar_button_rename.grid(row=3, column=0, padx=20, pady=10)

        self.sidebar_button_term = ctk.CTkButton(self.sidebar_frame, text="术语合并", font=self.font_normal, command=lambda: self.select_frame("term"))
        self.sidebar_button_term.grid(row=4, column=0, padx=20, pady=10)

        self.appearance_mode_label = ctk.CTkLabel(self.sidebar_frame, text="外观模式:", font=self.font_normal, anchor="w")
        self.appearance_mode_label.grid(row=7, column=0, padx=20, pady=(10, 0))
        self.appearance_mode_optionemenu = ctk.CTkOptionMenu(self.sidebar_frame, values=["System", "Light", "Dark"],
                                                                       font=self.font_normal,
                                                                       command=self.change_appearance_mode_event)
        self.appearance_mode_optionemenu.grid(row=8, column=0, padx=20, pady=(10, 20))
        
        # 主功能区
        self.frames = {}
        self.setup_clean_frame()
        self.setup_merge_frame()
        self.setup_rename_frame()
        self.setup_term_frame()
        
        # 底部日志区
        self.log_frame = ctk.CTkFrame(self, corner_radius=0, height=150)
        self.log_frame.grid(row=1, column=1, sticky="nsew", padx=10, pady=10)
        self.log_frame.grid_rowconfigure(0, weight=1)
        self.log_frame.grid_columnconfigure(0, weight=1)
        
        self.log_box = ctk.CTkTextbox(self.log_frame, font=self.font_normal)
        self.log_box.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.log("程序已启动...")
        if not HAS_DND:
            self.log("提示: 未检测到 tkinterdnd2，拖拽功能不可用。")
        else:
             self.log("提示: 支持文件拖拽。")

        self.select_frame("clean")

    def log(self, message):
        self.log_box.insert("end", str(message) + "\n")
        self.log_box.see("end")

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
        chk = ctk.CTkCheckBox(frame, text="SRT: 跳过合并短字幕", variable=self.clean_skip_merge_var, font=self.font_normal)
        chk.pack(pady=5, anchor="w")

        # 按钮区
        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(pady=10, fill="x")

        ctk.CTkButton(btn_frame, text="选择文件/文件夹 (清理SRT)", font=self.font_normal, command=lambda: self.run_task(self.task_clean_srt)).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="选择文件/文件夹 (格式化中文SRT)", font=self.font_normal, command=lambda: self.run_task(self.task_format_chs)).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="选择文件/文件夹 (缩放ASS描边)", font=self.font_normal, command=lambda: self.run_task(self.task_scale_ass)).pack(side="left", padx=5)
        
        # 拖拽区域容器
        dnd_container = ctk.CTkFrame(frame, fg_color="transparent")
        dnd_container.pack(pady=10, fill="both", expand=True)
        dnd_container.grid_columnconfigure(0, weight=1)
        dnd_container.grid_columnconfigure(1, weight=1)
        dnd_container.grid_columnconfigure(2, weight=1)

        # 1. 清理 SRT 区域
        self.dnd_clean = ctk.CTkFrame(dnd_container, border_width=2, border_color="gray")
        self.dnd_clean.grid(row=0, column=0, padx=5, sticky="nsew")
        
        lbl_clean = ctk.CTkLabel(self.dnd_clean, text="拖拽到此\n仅清理 SRT\n(移除统计)", font=self.font_normal, text_color="gray")
        lbl_clean.place(relx=0.5, rely=0.5, anchor="center")

        # 2. 格式化中文区域
        self.dnd_format = ctk.CTkFrame(dnd_container, border_width=2, border_color="gray")
        self.dnd_format.grid(row=0, column=1, padx=5, sticky="nsew")
        
        lbl_format = ctk.CTkLabel(self.dnd_format, text="拖拽到此\n格式化中文\n(标点处理)", font=self.font_normal, text_color="gray")
        lbl_format.place(relx=0.5, rely=0.5, anchor="center")

        # 3. ASS 缩放区域
        self.dnd_ass = ctk.CTkFrame(dnd_container, border_width=2, border_color="gray")
        self.dnd_ass.grid(row=0, column=2, padx=5, sticky="nsew")
        
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
        
        label = ctk.CTkLabel(frame, text="合并双语字幕 (SRT -> ASS)", font=self.font_title)
        label.pack(pady=10, anchor="w")
        
        info = ctk.CTkLabel(frame, text="说明: 要求文件夹内同时存在 .srt 和 .zh.srt (或 .zh-CN.srt) 文件。\n输出到 merge 子文件夹。", font=self.font_normal, justify="left")
        info.pack(pady=5, anchor="w")

        ctk.CTkButton(frame, text="选择文件夹合并", font=self.font_normal, command=lambda: self.run_task(self.task_merge_bilingual)).pack(pady=20, anchor="w")
        
        # 拖拽区域
        dnd_frame = ctk.CTkFrame(frame, border_width=2, border_color="gray")
        dnd_frame.pack(pady=20, fill="both", expand=True)
        dnd_label = ctk.CTkLabel(dnd_frame, text="拖拽文件夹到此处", font=self.font_normal, text_color="gray")
        dnd_label.place(relx=0.5, rely=0.5, anchor="center")

        if HAS_DND:
            dnd_frame.drop_target_register(DND_FILES)
            dnd_frame.dnd_bind('<<Drop>>', self.on_drop_merge)

    def setup_rename_frame(self):
        frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.frames["rename"] = frame
        
        label = ctk.CTkLabel(frame, text="批量重命名字幕", font=self.font_title)
        label.pack(pady=10, anchor="w")
        
        info = ctk.CTkLabel(frame, text="说明: 根据视频文件名 (SxxExx) 重命名对应的字幕文件。", font=self.font_normal, justify="left")
        info.pack(pady=5, anchor="w")
        
        ctk.CTkButton(frame, text="选择文件夹重命名", font=self.font_normal, command=lambda: self.run_task(self.task_rename_subs)).pack(pady=20, anchor="w")

        # 拖拽区域
        dnd_frame = ctk.CTkFrame(frame, border_width=2, border_color="gray")
        dnd_frame.pack(pady=20, fill="both", expand=True)
        dnd_label = ctk.CTkLabel(dnd_frame, text="拖拽文件夹到此处", font=self.font_normal, text_color="gray")
        dnd_label.place(relx=0.5, rely=0.5, anchor="center")

        if HAS_DND:
            dnd_frame.drop_target_register(DND_FILES)
            dnd_frame.dnd_bind('<<Drop>>', self.on_drop_rename)

    def setup_term_frame(self):
        frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.frames["term"] = frame
        
        label = ctk.CTkLabel(frame, text="合并术语表 (JSON)", font=self.font_title)
        label.pack(pady=10, anchor="w")
        
        self.term_file1 = ctk.StringVar()
        self.term_file2 = ctk.StringVar()
        
        ctk.CTkButton(frame, text="选择文件 1 (基础)", font=self.font_normal, command=lambda: self.select_file(self.term_file1)).pack(pady=5, anchor="w")
        self.entry_term1 = ctk.CTkEntry(frame, textvariable=self.term_file1, width=400, font=self.font_normal)
        self.entry_term1.pack(pady=0, anchor="w")
        
        ctk.CTkButton(frame, text="选择文件 2 (追加)", font=self.font_normal, command=lambda: self.select_file(self.term_file2)).pack(pady=5, anchor="w")
        self.entry_term2 = ctk.CTkEntry(frame, textvariable=self.term_file2, width=400, font=self.font_normal)
        self.entry_term2.pack(pady=0, anchor="w")

        if HAS_DND:
            self.entry_term1.drop_target_register(DND_FILES)
            self.entry_term1.dnd_bind('<<Drop>>', lambda e: self.on_drop_assign(e, self.term_file1))
            self.entry_term2.drop_target_register(DND_FILES)
            self.entry_term2.dnd_bind('<<Drop>>', lambda e: self.on_drop_assign(e, self.term_file2))
        
        ctk.CTkButton(frame, text="开始合并", font=self.font_normal, command=lambda: self.run_task(self.task_merge_terms)).pack(pady=20, anchor="w")

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
        folders = [f for f in files if os.path.isdir(f)]
        if folders:
            self.run_task(lambda: self.task_merge_bilingual(folders[0])) # 只处理第一个文件夹
        else:
            self.log("请拖拽文件夹")

    def on_drop_rename(self, event):
        files = self.parse_drop_files(event.data)
        if not files: return
        folders = [f for f in files if os.path.isdir(f)]
        if folders:
            self.run_task(lambda: self.task_rename_subs(folders[0]))
        else:
            self.log("请拖拽文件夹")

    def parse_drop_files(self, data):
        # tkinterdnd2 返回的路径如果是包含空格的，会用 {} 包裹
        # 简单解析
        if data.startswith('{') and data.endswith('}'):
            # 这是一个简单这种，实际上可能多个文件 {file 1} {file 2}
            import re
            return re.findall(r'\{(.+?)\}|(\S+)', data) # 粗略解析，待完善
            # 更简单的处理：
            # data 这里通常是 "{path1} {path2}" 或 "path1 path2"
        # 直接使用 split 可能有问题。这里暂时只支持单个文件或标准列表
        # Windows 下通常是 {path}
        paths = []
        if data.startswith('{'):
            parts = data.split('} {')
            for p in parts:
                paths.append(p.strip('{}'))
        else:
            paths.append(data)
        return paths

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

    def task_merge_bilingual(self, folder=None):
        if not folder:
            paths = self.get_paths("folder")
            if not paths: return
            folder = paths[0]
        self.log(f"开始合并双语字幕: {folder}")
        for msg in SubtitleTool.merge_bilingual_srt(folder):
            self.log(msg)
        self.log("任务结束")

    def task_rename_subs(self, folder=None):
        if not folder:
             paths = self.get_paths("folder")
             if not paths: return
             folder = paths[0]
        self.log(f"开始重命名字幕: {folder}")
        for msg in SubtitleTool.rename_subtitles(folder):
            self.log(msg)
        self.log("任务结束")

    def task_merge_terms(self):
        f1 = self.term_file1.get()
        f2 = self.term_file2.get()
        if not f1 or not f2:
            self.log("请选择两个 JSON 文件")
            return
        
        output = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not output: return

        self.log("开始合并术语表...")
        for msg in SubtitleTool.merge_terms(f1, f2, output):
            self.log(msg)
        self.log("任务结束")

if __name__ == "__main__":
    app = App()
    app.mainloop()
