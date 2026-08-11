# Subtitle Process - AI Agent Guidelines (AGENTS.md)

## 1. 项目概览 (Project Overview)
- **技术栈**: Python 3.x / CustomTkinter / tkinterdnd2-universal / FFmpeg & MKVToolNix
- **目录架构**:
  - `app_ui.py`: 主程序 GUI 入口
  - `tools/`: 核心业务逻辑（字幕清理、双语合并、帧率转换、路径处理、字幕提取）
  - `ui/`: GUI 界面层（ CustomTkinter Frame 页面组件）
  - `verify/`: 自动化与手工验证测试脚本
  - `version.py` & `CHANGELOG.md`: 版本号定义与变更日志

## 2. 编码与路径规范 (Coding Guidelines)
- **路径安全**: 涉及文件与路径处理时，优先使用 `tools.path_utils` (`normalize_path`, `get_safe_open_path`)，确保 Windows 8.3 短路径恢复与长路径兼容。
- **编码处理**: 字幕文件写出统一显式指定 `encoding='utf-8'` 和 LF。
- **架构解耦**: 保持 UI 层 (`ui/`) 与业务层 (`tools/`) 分离，业务函数应可单独在无 GUI 环境下测试与运行。

## 3. AI 行为准则 (Guardrails)
- **严禁静默吞异常**: 出现处理错误必须记录日志或抛出异常，以便 UI 实时反馈给用户。
- **尊重拖拽交互**: 谨慎修改拖拽区域（`tkinterdnd2`）与事件绑定逻辑。
- **修改前核对定义**: 修改业务正则表达式或时间轴解析逻辑前，先查阅 `tools/` 中的现有实现，防止打破既有格式匹配。

## 4. 提交规范 (Commit Standard)
- **编写 Changelog**:
  - 每次合并分支代码前，主动更新 `CHANGELOG.md`。
- **Git 提交格式**: 遵循项目现有 Conventional Commits 格式（如 `feat: ...`, `fix: ...`, `chore: bump version to X.Y.Z`）。
- **版本发布**: 除非主动要求，否则不要自己修改 `version.py`。
