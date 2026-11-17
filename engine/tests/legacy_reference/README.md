# 旧工具箱 golden 基准（冻结）

这里是从 v1 CustomTkinter 工具箱（存档分支 `archive/legacy-toolbox`）冻结过来的
领域算法，仅用于 `engine/tests/` 的逐字节 golden 对比：

| 文件 | 被对比的引擎实现 |
|---|---|
| `chs_srt_format.py` / `srt_process.py` | `domain/clean.py` |
| `subtitle_extractor.py` | `domain/media.py` |
| `merge_srt.py` | `domain/merge.py` |
| `fps_converter.py` / `time_shifter.py` | `domain/timing.py` |
| `ass_outlinescale.py` | `domain/outline.py` |

- **不要修改这些文件**，也不要在生产代码中导入它们。算法若需变化，请改
  `engine/src/subtitle_engine/domain/` 并同步更新 golden 预期。
- 旧版完整实现（GUI、`subtitle_api.py`、`path_utils.py` 等）保留在
  `archive/legacy-toolbox` 分支，不再进入主线。
- `merge_srt.py` 仅把 `from tools.chs_srt_format` 改为包内相对导入，行为不变。
