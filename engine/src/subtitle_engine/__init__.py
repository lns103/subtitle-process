"""字幕流水线引擎。

协议：JSON-RPC 2.0 over stdio（JSONL），详见 ``docs/pipeline-v2/PROTOCOL.md``。
"""

from .version import PROTOCOL_VERSION, __version__

__all__ = ["PROTOCOL_VERSION", "__version__"]
