import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog
import threading
import os
from tools.subtitle_api import SubtitleTool

try:
    from tkinterdnd2 import DND_FILES
    HAS_DND = True
except ImportError:
    HAS_DND = False

class ExtractFrame(ctk.CTkFrame):
    def __init__(self, master, app, **kwargs):
        super().__init__(master, **kwargs)
        self.app = app
        
        # 使用 Grid 布局以确保底部按钮可见性
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1) # Row 4 (Scroll) expands

        # Row 0: Title
        label = ctk.CTkLabel(self, text="字幕提取 (FFmpeg)", font=self.app.font_title)
        label.grid(row=0, column=0, sticky="w", padx=10, pady=10)
        
        # Row 1: File Selection
        self.extract_file_var = ctk.StringVar(value="未选择文件")
        
        file_frame = ctk.CTkFrame(self, fg_color="transparent")
        file_frame.grid(row=1, column=0, sticky="ew", padx=0, pady=5)
        
        ctk.CTkButton(file_frame, text="选择视频文件", font=self.app.font_normal, command=self.select_video_file).pack(side="left", padx=(10, 10))
        self.lbl_extract_file = ctk.CTkLabel(file_frame, textvariable=self.extract_file_var, font=self.app.font_normal, text_color="gray", anchor="w")
        self.lbl_extract_file.pack(side="left", fill="x", expand=True)

        # Row 2: DnD
        if HAS_DND:
            dnd_frame = ctk.CTkFrame(self, border_width=2, border_color="gray", height=60)
            dnd_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=10)
            dnd_frame.pack_propagate(False) 
            
            dnd_label = ctk.CTkLabel(dnd_frame, text="拖拽视频文件到此处 (MP4 / MKV)", font=self.app.font_normal, text_color="gray")
            dnd_label.place(relx=0.5, rely=0.5, anchor="center")
            
            dnd_frame.drop_target_register(DND_FILES)
            dnd_frame.dnd_bind('<<Drop>>', self.on_drop_extract)

        # Row 3: Track Label
        ctk.CTkLabel(self, text="可用字幕轨道:", font=self.app.font_bold).grid(row=3, column=0, sticky="w", padx=10, pady=(10, 5))
        
        # Row 4: Scroll List (Expands)
        self.tracks_scroll = ctk.CTkScrollableFrame(self, height=100)
        self.tracks_scroll.grid(row=4, column=0, sticky="nsew", padx=10, pady=5)
        
        # Row 5: Button (Fixed at bottom)
        ctk.CTkButton(self, text="开始提取选中字幕", font=self.app.font_large_bold, height=40, command=self.task_dev_extract).grid(row=5, column=0, sticky="ew", padx=10, pady=10)

        # 内部变量
        self.current_video_path = None
        self.current_video_info = None
        self.track_vars = [] # list of (dict_info, BooleanVar)

    def on_drop_extract(self, event):
        files = self.app.parse_drop_files(event.data)
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
        self.app.log(f"正在分析视频文件: {filepath} ...")
        
        # 清空列表
        for widget in self.tracks_scroll.winfo_children():
            widget.destroy()
        self.track_vars = []
        
        threading.Thread(target=self.task_analyze_video, args=(filepath,)).start()

    def task_analyze_video(self, filepath):
        if not SubtitleTool: 
             self.app.log("Error: Tools not loaded.")
             return
             
        info = SubtitleTool.get_video_info(filepath)
        if not info:
            self.app.log("无法获取媒体信息 (ffprobe 失败?)")
            return
            
        self.current_video_info = info
            
        if info.get("warnings"):
            for w in info["warnings"]:
                self.app.log(w)
            
        # Get defaults
        recommendations = SubtitleTool.get_extraction_recommendation(info)
        
        # Update UI in main thread
        self.after(0, lambda: self.render_track_list(info, recommendations))

    def render_track_list(self, info, recommendations):
        subs = info.get("subtitles", [])
        if not subs:
            ctk.CTkLabel(self.tracks_scroll, text="未找到字幕轨道", font=self.app.font_normal).pack(pady=10)
            self.app.log(f"分析完成: 无字幕轨道")
            return
            
        audio_info = f"Audio: {len(info.get('audio_langs', []))} tracks (Default: {info.get('default_audio_lang', 'None')})"
        self.app.log(f"分析完成: {len(subs)} 个字幕轨道. {audio_info}")
        
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
            
            chk = ctk.CTkCheckBox(track_frame, text=display_text, variable=var, font=self.app.font_normal)
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
        self.app.run_task(self.task_dev_extract_run)

    def task_dev_extract_run(self):
        if not self.current_video_path:
            self.app.log("请先选择视频文件")
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
            self.app.log("未选择任何轨道")
            return
            
        self.app.log(f"开始提取 {len(selected_subs)} 个轨道...")
        
        total_duration = 0
        if self.current_video_info:
            total_duration = self.current_video_info.get("duration", 0)
            
        if SubtitleTool is None:
            self.app.log("Error: SubtitleTool not loaded.")
            return

        for msg in SubtitleTool.extract_subtitles_stream(self.current_video_path, selected_subs, total_duration=total_duration):
            if "提取进度" in msg:
                self.app.log_progress(msg)
            else:
                self.app.log(msg)
        self.app.log("提取任务结束")
