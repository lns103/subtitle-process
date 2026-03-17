import customtkinter as ctk
import threading
import re
from tools.subtitle_api import SubtitleTool

try:
    from tkinterdnd2 import DND_FILES
    HAS_DND = True
except ImportError:
    HAS_DND = False

# --- ASS 字段校验规则 ---
_COLOR_RE = re.compile(r"^&H[0-9A-Fa-f]{8}$")

def _v_str(s):
    """非空字符串, 不含逗号"""
    return bool(s) and "," not in s

def _v_pos_num(s):
    """正数 (整数或小数)"""
    try: return float(s) > 0
    except: return False

def _v_num(s):
    """任意数值"""
    try: float(s); return True
    except: return False

def _v_nn_num(s):
    """非负数值"""
    try: return float(s) >= 0
    except: return False

def _v_nn_int(s):
    """非负整数"""
    try: return int(s) >= 0 and "." not in s
    except: return False

def _v_color(s):
    """ASS 颜色格式 &HNNNNNNNN"""
    return bool(_COLOR_RE.match(s))

def _v_bold(s):
    """0, 1 或 -1"""
    return s in ("0", "1", "-1")

def _v_bool01(s):
    """0 或 1"""
    return s in ("0", "1")

def _v_border_style(s):
    """1 或 3"""
    return s in ("1", "3")

def _v_alignment(s):
    """1-9"""
    return s in [str(i) for i in range(1, 10)]

# 每个字段对应的校验函数
_FIELD_VALIDATORS = {
    "Fontname":         _v_str,
    "Fontsize":         _v_pos_num,
    "PrimaryColour":    _v_color,
    "SecondaryColour":  _v_color,
    "OutlineColour":    _v_color,
    "BackColour":       _v_color,
    "Bold":             _v_bold,
    "Italic":           _v_bool01,
    "Underline":        _v_bool01,
    "StrikeOut":        _v_bool01,
    "ScaleX":           _v_pos_num,
    "ScaleY":           _v_pos_num,
    "Spacing":          _v_num,
    "Angle":            _v_num,
    "BorderStyle":      _v_border_style,
    "Outline":          _v_nn_num,
    "Shadow":           _v_nn_num,
    "Alignment":        _v_alignment,
    "MarginL":          _v_nn_int,
    "MarginR":          _v_nn_int,
    "MarginV":          _v_nn_int,
    "Encoding":         _v_nn_int,
}


class MergeStyleConfigDialog(ctk.CTkToplevel):
    def __init__(self, parent, config, save_callback):
        super().__init__(parent)
        self.title("双语合并样式自定义")
        self.geometry("900x780")
        self.config = config
        self.save_callback = save_callback
        
        self.font_normal = ctk.CTkFont(family="Microsoft YaHei", size=12)
        self.font_bold = ctk.CTkFont(family="Microsoft YaHei", size=12, weight="bold")

        # Layout: row0=resolution, row1=import area, row2=style panels (expand), row3=bottom
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)
        
        # Default config reference (to restore)
        self.default_l1_def = "黑体, 60, &H00EEEEEE, &HF0000000, &H00000000, &H32000000, 0, 0, 0, 0, 100, 100, 0, 0, 1, 1.5, 0, 2, 18, 18, 18, 1"
        self.default_l2_def = "Arial, 40, &H00EEEEEE, &HF0000000, &H00000000, &H32000000, 0, 0, 0, 0, 100, 100, 0, 0, 1, 1.5, 0, 2, 18, 18, 18, 1"

        # Resolution
        res_frame = ctk.CTkFrame(self, fg_color="transparent")
        res_frame.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 0))
        ctk.CTkLabel(res_frame, text="分辨率 (PlayResX):", font=self.font_bold).pack(side="left", padx=5)
        self.var_playresx = ctk.StringVar(value=str(self.config.get("merge_playresx", 1920)))
        self.entry_playresx = ctk.CTkEntry(res_frame, textvariable=self.var_playresx, font=self.font_normal, width=80)
        self.entry_playresx.pack(side="left", padx=5)
        self.var_playresx.trace_add("write", lambda *_: self._live_validate_int(self.entry_playresx, self.var_playresx))
        
        ctk.CTkLabel(res_frame, text="(PlayResY):", font=self.font_bold).pack(side="left", padx=5)
        self.var_playresy = ctk.StringVar(value=str(self.config.get("merge_playresy", 1080)))
        self.entry_playresy = ctk.CTkEntry(res_frame, textvariable=self.var_playresy, font=self.font_normal, width=80)
        self.entry_playresy.pack(side="left", padx=5)
        self.var_playresy.trace_add("write", lambda *_: self._live_validate_int(self.entry_playresy, self.var_playresy))

        # --- Import area ---
        import_frame = ctk.CTkFrame(self, fg_color="transparent")
        import_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(5, 0))

        import_top = ctk.CTkFrame(import_frame, fg_color="transparent")
        import_top.pack(fill="x")
        ctk.CTkLabel(import_top, text="粘贴完整 Style 行导入（按样式名称匹配）:", font=self.font_normal).pack(side="left")
        ctk.CTkButton(import_top, text="导入样式", font=self.font_bold, width=90, command=self._import_styles).pack(side="right")

        self.import_textbox = ctk.CTkTextbox(import_frame, height=55, font=self.font_normal)
        self.import_textbox.pack(fill="x", pady=(3, 0))
        self.import_textbox.insert("0.0", "Style: Name,Fontname,Fontsize,PrimaryColour,...")
        self.import_textbox.configure(text_color="gray")
        self.import_textbox.bind("<FocusIn>", self._import_tb_focus_in)
        self.import_textbox.bind("<FocusOut>", self._import_tb_focus_out)

        self.import_error_label = ctk.CTkLabel(import_frame, text="", font=self.font_normal, text_color="#E06666", anchor="w", height=20)
        self.import_error_label.pack(fill="x")

        # Parameters definition
        self.ass_fields = [
            ("Fontname", "字体名称"),    ("Fontsize", "字体大小"),
            ("PrimaryColour", "主要颜色"),("SecondaryColour", "次要颜色"),
            ("OutlineColour", "边框颜色"),("BackColour", "阴影颜色"),
            ("Bold", "粗体(0/1/-1)"),      ("Italic", "斜体(0/1)"),
            ("Underline", "下划线(0/1)"), ("StrikeOut", "删除线(0/1)"),
            ("ScaleX", "横向缩放(%)"),   ("ScaleY", "纵向缩放(%)"),
            ("Spacing", "字间距"),       ("Angle", "旋转角度"),
            ("BorderStyle", "边框样式"),  ("Outline", "边框宽度"),
            ("Shadow", "阴影深度"),       ("Alignment", "对齐方式(1-9)"),
            ("MarginL", "左边距"),       ("MarginR", "右边距"),
            ("MarginV", "垂直边距"),     ("Encoding", "编码"),
        ]

        # Scrollable frames for L1 and L2
        self.frame_l1 = ctk.CTkScrollableFrame(self)
        self.frame_l1.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.frame_l2 = ctk.CTkScrollableFrame(self)
        self.frame_l2.grid(row=2, column=1, sticky="nsew", padx=10, pady=(0, 10))

        # Vars and entry widgets
        self.vars_l1 = []
        self.vars_l2 = []
        self.entries_l1 = []
        self.entries_l2 = []
        
        # Meta info
        self.var_l1_name = ctk.StringVar(value=self.config.get("merge_lang1_style_name", "Translate"))
        self.var_l2_name = ctk.StringVar(value=self.config.get("merge_lang2_style_name", "Original"))
        self.var_author = ctk.StringVar(value=self.config.get("merge_author", "default"))
        self.var_comment = ctk.StringVar(value=self.config.get("merge_comment", ""))

        self.entry_l1_name = self.setup_panel(self.frame_l1, "翻译样式 (Lang 1)", self.var_l1_name, self.config.get("merge_lang1_style_def", self.default_l1_def), self.vars_l1, self.entries_l1)
        self.entry_l2_name = self.setup_panel(self.frame_l2, "原始样式 (Lang 2)", self.var_l2_name, self.config.get("merge_lang2_style_def", self.default_l2_def), self.vars_l2, self.entries_l2)
        
        # Bottom frame
        bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        bottom_frame.grid(row=3, column=0, columnspan=2, sticky="ew", padx=10, pady=10)
        
        ctk.CTkLabel(bottom_frame, text="Author:", font=self.font_normal).pack(side="left", padx=5)
        ctk.CTkEntry(bottom_frame, textvariable=self.var_author, font=self.font_normal, width=100).pack(side="left", padx=5)
        
        ctk.CTkLabel(bottom_frame, text="Comment:", font=self.font_normal).pack(side="left", padx=5)
        ctk.CTkEntry(bottom_frame, textvariable=self.var_comment, font=self.font_normal, width=200).pack(side="left", padx=5)

        ctk.CTkButton(bottom_frame, text="保存修改", font=self.font_bold, command=self.save_and_close).pack(side="right", padx=10)
        ctk.CTkButton(bottom_frame, text="一键恢复默认", font=self.font_normal, fg_color="#E06666", hover_color="#CC0000", command=self.restore_defaults).pack(side="right", padx=10)
        
        # Grab set
        self.transient(parent)
        self.grab_set()

    def setup_panel(self, parent, title, name_var, style_def_str, vars_list, entries_list):
        ctk.CTkLabel(parent, text=title, font=self.font_bold).pack(pady=10, anchor="w")
        
        # Name
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=2)
        ctk.CTkLabel(row, text="样式名称\nName", width=120, anchor="w", justify="left", font=self.font_normal).pack(side="left")
        name_entry = ctk.CTkEntry(row, textvariable=name_var, font=self.font_normal)
        name_entry.pack(side="left", fill="x", expand=True)
        name_var.trace_add("write", lambda *_: self._live_validate_text(name_entry, name_var))

        ctk.CTkFrame(parent, height=2, fg_color="gray").pack(fill="x", pady=10)

        # Parse style def
        parts = [p.strip() for p in style_def_str.split(",")]
        while len(parts) < len(self.ass_fields):
            parts.append("")
            
        for i, (f_key, f_label) in enumerate(self.ass_fields):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", pady=2)
            lbl = f"{f_key}\n{f_label}"
            ctk.CTkLabel(row, text=lbl, width=120, anchor="w", justify="left", font=self.font_normal).pack(side="left")
            val = parts[i] if i < len(parts) else ""
            var = ctk.StringVar(value=val)
            vars_list.append(var)
            entry = ctk.CTkEntry(row, textvariable=var, font=self.font_normal)
            entry.pack(side="left", fill="x", expand=True)
            entries_list.append(entry)
            validator = _FIELD_VALIDATORS.get(f_key, _v_str)
            var.trace_add("write", lambda *_, e=entry, v=var, fn=validator: self._mark_entry(e, fn(v.get().strip())))
        
        return name_entry

    def restore_defaults(self):
        from tkinter import messagebox
        if not messagebox.askyesno("确认恢复", "确定要将样式参数恢复为默认值吗？\n\n（只恢复字体、颜色、分辨率及排版样式等参数，\n不会改变样式名、作者和注释）", parent=self):
            return
        
        parts_l1 = [p.strip() for p in self.default_l1_def.split(",")]
        for i, var in enumerate(self.vars_l1):
            if i < len(parts_l1):
                var.set(parts_l1[i])
                
        parts_l2 = [p.strip() for p in self.default_l2_def.split(",")]
        for i, var in enumerate(self.vars_l2):
            if i < len(parts_l2):
                var.set(parts_l2[i])

        self.var_playresx.set("1920")
        self.var_playresy.set("1080")

    # --- Import helpers ---
    _STYLE_LINE_RE = re.compile(r'^Style:\s*([^,]+),(.+)$')

    def _import_tb_focus_in(self, event):
        """清除占位文字"""
        content = self.import_textbox.get("0.0", "end").strip()
        if content == "Style: Name,Fontname,Fontsize,PrimaryColour,...":
            self.import_textbox.delete("0.0", "end")
            self.import_textbox.configure(text_color=ctk.ThemeManager.theme["CTkTextbox"]["text_color"])

    def _import_tb_focus_out(self, event):
        """恢复占位文字"""
        content = self.import_textbox.get("0.0", "end").strip()
        if not content:
            self.import_textbox.insert("0.0", "Style: Name,Fontname,Fontsize,PrimaryColour,...")
            self.import_textbox.configure(text_color="gray")

    def _set_import_error(self, msg):
        """设置导入区域的错误/成功状态"""
        if msg:
            self.import_textbox.configure(border_color="#E06666")
            self.import_error_label.configure(text=msg, text_color="#E06666")
        else:
            self.import_textbox.configure(border_color=ctk.ThemeManager.theme["CTkTextbox"]["border_color"])
            self.import_error_label.configure(text="")

    def _import_styles(self):
        """解析文本框中的 Style 行, 按名称匹配填入对应面板。
        支持可选的 Format: 行来确定字段映射顺序。
        缺少或未知的字段会被跳过并给出提示。"""
        raw = self.import_textbox.get("0.0", "end").strip()
        if not raw or raw == "Style: Name,Fontname,Fontsize,PrimaryColour,...":
            self._set_import_error("请先粘贴 Style 行")
            return

        l1_name = self.var_l1_name.get().strip()
        l2_name = self.var_l2_name.get().strip()
        # 已知字段名 -> 在 ass_fields 中的索引
        known_fields = {f_key: i for i, (f_key, _) in enumerate(self.ass_fields)}
        warnings = []
        errors = []
        matched = []

        # 1. 解析 Format 行（如存在），确定字段映射
        format_fields = None  # None = 使用默认顺序
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        style_lines = []

        for line in lines:
            if line.lower().startswith("format:"):
                # 解析 Format 行
                fmt_body = line.split(":", 1)[1]
                fmt_names = [n.strip() for n in fmt_body.split(",")]
                # 第一个字段固定为 Name，跳过
                if fmt_names and fmt_names[0].lower() == "name":
                    fmt_names = fmt_names[1:]
                # 建立映射：位置 -> ass_fields 索引，跳过未知字段
                format_fields = []
                unknown = []
                for fn in fmt_names:
                    if fn in known_fields:
                        format_fields.append(known_fields[fn])
                    else:
                        format_fields.append(None)  # 未知字段，跳过
                        unknown.append(fn)
                if unknown:
                    warnings.append(f"忽略未知字段: {', '.join(unknown)}")
            elif self._STYLE_LINE_RE.match(line):
                style_lines.append(line)
            else:
                errors.append(f"格式不合法: {line[:50]}")

        if not style_lines:
            self._set_import_error("未找到有效的 Style 行")
            return

        # 2. 逐行处理 Style
        for line in style_lines:
            m = self._STYLE_LINE_RE.match(line)
            name = m.group(1).strip()
            params = [p.strip() for p in m.group(2).split(",")]

            # 确定目标面板
            if name == l1_name:
                target_vars = self.vars_l1
                panel_label = f"Lang1 ({name})"
            elif name == l2_name:
                target_vars = self.vars_l2
                panel_label = f"Lang2 ({name})"
            else:
                errors.append(f"名称不匹配: \"{name}\" (当前: \"{l1_name}\" / \"{l2_name}\")")
                continue

            # 按字段映射写入
            filled = []
            skipped_invalid = []

            if format_fields is not None:
                # 有 Format 行，按映射写入
                for pos, param_val in enumerate(params):
                    if pos >= len(format_fields):
                        break
                    field_idx = format_fields[pos]
                    if field_idx is None:
                        continue  # 未知字段，跳过
                    f_key = self.ass_fields[field_idx][0]
                    validator = _FIELD_VALIDATORS.get(f_key, _v_str)
                    if validator(param_val):
                        target_vars[field_idx].set(param_val)
                        filled.append(f_key)
                    else:
                        skipped_invalid.append(f_key)

                # 检查哪些已知字段没有被覆盖
                covered = {format_fields[p] for p in range(min(len(params), len(format_fields))) if format_fields[p] is not None}
                missing = [self.ass_fields[i][0] for i in range(len(self.ass_fields)) if i not in covered]
                if missing:
                    warnings.append(f"\"{name}\" 保留原值: {', '.join(missing)}")
            else:
                # 无 Format 行，按默认顺序填入（允许参数不足）
                for i, param_val in enumerate(params):
                    if i >= len(self.ass_fields):
                        break
                    f_key = self.ass_fields[i][0]
                    validator = _FIELD_VALIDATORS.get(f_key, _v_str)
                    if validator(param_val):
                        target_vars[i].set(param_val)
                        filled.append(f_key)
                    else:
                        skipped_invalid.append(f_key)

                if len(params) < len(self.ass_fields):
                    missing = [self.ass_fields[i][0] for i in range(len(params), len(self.ass_fields))]
                    warnings.append(f"\"{name}\" 保留原值: {', '.join(missing)}")

            if skipped_invalid:
                warnings.append(f"\"{name}\" 跳过不合法: {', '.join(skipped_invalid)}")

            matched.append(panel_label)

        # 3. 报告结果
        if errors:
            all_msgs = errors + warnings
            self._set_import_error("; ".join(all_msgs))
        elif warnings:
            # 部分成功 — 用橙色提示
            self.import_textbox.configure(border_color="#E8A830")
            self.import_error_label.configure(text=f"已导入 {', '.join(matched)}; {'; '.join(warnings)}", text_color="#E8A830")
        else:
            self._set_import_error("")
            self.import_textbox.delete("0.0", "end")
            self.import_textbox.insert("0.0", "Style: Name,Fontname,Fontsize,PrimaryColour,...")
            self.import_textbox.configure(text_color="gray")

    @staticmethod
    def _mark_entry(entry, valid):
        """标记输入框: 无效时红色边框, 有效时恢复默认"""
        entry.configure(border_color="#E06666" if not valid else ctk.ThemeManager.theme["CTkEntry"]["border_color"])

    def _is_positive_int(self, s):
        try:
            return int(s) > 0
        except (ValueError, TypeError):
            return False

    def _live_validate_int(self, entry, var):
        """实时校验正整数"""
        self._mark_entry(entry, self._is_positive_int(var.get().strip()))

    def _live_validate_text(self, entry, var):
        """实时校验非空且不含逗号"""
        val = var.get().strip()
        self._mark_entry(entry, bool(val) and "," not in val)

    def save_and_close(self):
        from tkinter import messagebox
        has_error = False

        # 1. 校验分辨率
        for entry, var in [(self.entry_playresx, self.var_playresx), (self.entry_playresy, self.var_playresy)]:
            ok = self._is_positive_int(var.get().strip())
            self._mark_entry(entry, ok)
            if not ok:
                has_error = True

        # 2. 校验样式名称
        for entry, var in [(self.entry_l1_name, self.var_l1_name), (self.entry_l2_name, self.var_l2_name)]:
            val = var.get().strip()
            ok = _v_str(val)
            self._mark_entry(entry, ok)
            if not ok:
                has_error = True

        # 3. 按字段类型校验各项参数
        for entries, vars_list in [(self.entries_l1, self.vars_l1), (self.entries_l2, self.vars_l2)]:
            for i, (entry, var) in enumerate(zip(entries, vars_list)):
                f_key = self.ass_fields[i][0]
                validator = _FIELD_VALIDATORS.get(f_key, _v_str)
                ok = validator(var.get().strip())
                self._mark_entry(entry, ok)
                if not ok:
                    has_error = True

        if has_error:
            messagebox.showwarning("保存失败", "请修正标红的参数后再保存", parent=self)
            return

        def_l1 = ", ".join([v.get().strip() for v in self.vars_l1])
        def_l2 = ", ".join([v.get().strip() for v in self.vars_l2])
        
        self.config["merge_lang1_style_name"] = self.var_l1_name.get().strip()
        self.config["merge_lang2_style_name"] = self.var_l2_name.get().strip()
        self.config["merge_lang1_style_def"] = def_l1
        self.config["merge_lang2_style_def"] = def_l2
        self.config["merge_author"] = self.var_author.get()
        self.config["merge_comment"] = self.var_comment.get()
        self.config["merge_playresx"] = int(self.var_playresx.get().strip())
        self.config["merge_playresy"] = int(self.var_playresy.get().strip())
        
        if self.save_callback:
            self.save_callback()
            
        self.destroy()

class MergeFrame(ctk.CTkFrame):
    def __init__(self, master, app, **kwargs):
        super().__init__(master, **kwargs)
        self.app = app
        
        # 顶部布局分两列
        top_frame = ctk.CTkFrame(self, fg_color="transparent")
        top_frame.pack(fill="x", pady=10)
        
        left_col = ctk.CTkFrame(top_frame, fg_color="transparent")
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 10))
        
        right_col = ctk.CTkFrame(top_frame, fg_color="transparent")
        right_col.pack(side="right", fill="both", expand=True)

        label = ctk.CTkLabel(left_col, text="合并双语字幕 (SRT -> ASS)", font=self.app.font_title)
        label.pack(pady=10, anchor="w")
        
        info = ctk.CTkLabel(left_col, text="说明: 要求文件夹内同时存在原语言和翻译语言文件。\n默认为 .srt 和 .zh.srt。\n也可直接拖拽配对的源语言 .srt 文件。", font=self.app.font_normal, justify="left")
        info.pack(pady=5, anchor="w")

        ctk.CTkButton(left_col, text="选择文件夹合并", font=self.app.font_normal, command=self.task_merge_bilingual).pack(pady=20, anchor="w")
        
        # 右侧配置项
        def add_config_row(parent, text, key):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=text, width=120, anchor="w", font=self.app.font_normal).pack(side="left")
            var = ctk.StringVar(value=self.app.config.get(key, ""))
            def on_change(*args):
                self.app.config[key] = var.get()
                self.app.save_config()
            var.trace_add("write", on_change)
            entry = ctk.CTkEntry(row, textvariable=var, font=self.app.font_normal)
            entry.pack(side="left", fill="x", expand=True)
            return var

        ctk.CTkLabel(right_col, text="基本设置 (Basic)", font=self.app.font_bold).pack(pady=(0, 5), anchor="w")
        self.var_merge_suffix = add_config_row(right_col, "翻译文件后缀:", "merge_translated_suffix")
        self.var_merge_out_suffix = add_config_row(right_col, "合并后后缀:", "merge_output_suffix")

        ctk.CTkLabel(right_col, text="高级设置 (Advanced)", font=self.app.font_bold).pack(pady=(20, 5), anchor="w")
        ctk.CTkButton(right_col, text="高级样式自定义...", font=self.app.font_normal, command=self.open_style_config_dialog).pack(fill="x", pady=5)
        
        # 拖拽区域
        dnd_frame = ctk.CTkFrame(self, border_width=2, border_color="gray")
        dnd_frame.pack(pady=20, fill="both", expand=True)
        dnd_label = ctk.CTkLabel(dnd_frame, text="拖拽文件夹或文件到此处", font=self.app.font_normal, text_color="gray")
        dnd_label.place(relx=0.5, rely=0.5, anchor="center")

        if HAS_DND:
            dnd_frame.drop_target_register(DND_FILES)
            dnd_frame.dnd_bind('<<Drop>>', self.on_drop_merge)

    def open_style_config_dialog(self):
        if hasattr(self, "style_dialog") and self.style_dialog.winfo_exists():
            self.style_dialog.lift()
            return
        self.style_dialog = MergeStyleConfigDialog(self, self.app.config, self.app.save_config)

    def on_drop_merge(self, event):
        files = self.app.parse_drop_files(event.data)
        if not files: return
        self.app.run_task(lambda: self.task_merge_bilingual_run(files))

    def task_merge_bilingual(self):
        paths = self.app.get_paths("folder")
        if not paths: return
        self.app.run_task(lambda: self.task_merge_bilingual_run(paths))

    def task_merge_bilingual_run(self, paths):
        if SubtitleTool is None:
            self.app.log("Error: SubtitleTool not loaded.")
            return

        kwargs = {
            "translated_suffix": self.app.config.get("merge_translated_suffix"),
            "lang1_style_name": self.app.config.get("merge_lang1_style_name"),
            "lang1_style_def": self.app.config.get("merge_lang1_style_def"),
            "lang2_style_name": self.app.config.get("merge_lang2_style_name"),
            "lang2_style_def": self.app.config.get("merge_lang2_style_def"),
            "author": self.app.config.get("merge_author"),
            "comment": self.app.config.get("merge_comment"),
            "output_suffix": self.app.config.get("merge_output_suffix"),
            "playresx": self.app.config.get("merge_playresx"),
            "playresy": self.app.config.get("merge_playresy")
        }
            
        self.app.log(f"开始合并双语字幕: {len(paths)} 个项目")
        for msg in SubtitleTool.merge_bilingual_srt(paths, **kwargs):
            self.app.log(msg)
        self.app.log("任务结束")
