"""系统钥匙串封装（TASKBOOK §11.9）。

Windows 下由 ``keyring`` 写入 Credential Manager。业务代码只通过本模块读写
API Key，禁止把 Key 写入 SQLite、配方、日志或异常信息。
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)

SERVICE_NAME = "subtitle-process"


class SecretStoreError(RuntimeError):
    """钥匙串不可用或读写失败。"""


class SecretStoreProtocol(Protocol):
    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


class SecretStore:
    """基于 ``keyring`` 的钥匙串实现。"""

    def __init__(self, service: str = SERVICE_NAME) -> None:
        self._service = service

    def get(self, name: str) -> str | None:
        import keyring
        from keyring.errors import KeyringError

        try:
            value = keyring.get_password(self._service, name)
        except KeyringError as exc:
            raise SecretStoreError(f"读取系统钥匙串失败: {name}") from exc
        return value or None

    def set(self, name: str, value: str) -> None:
        import keyring
        from keyring.errors import KeyringError

        try:
            keyring.set_password(self._service, name, value)
        except KeyringError as exc:
            raise SecretStoreError(f"写入系统钥匙串失败: {name}") from exc

    def delete(self, name: str) -> None:
        import keyring
        from keyring.errors import KeyringError, PasswordDeleteError

        try:
            keyring.delete_password(self._service, name)
        except PasswordDeleteError:
            # 删除不存在的项是幂等操作，不算错误。
            return
        except KeyringError as exc:
            raise SecretStoreError(f"删除系统钥匙串项失败: {name}") from exc


class InMemorySecretStore:
    """测试用内存实现；生产环境不得使用。"""

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._values = dict(initial or {})

    def get(self, name: str) -> str | None:
        return self._values.get(name) or None

    def set(self, name: str, value: str) -> None:
        self._values[name] = value

    def delete(self, name: str) -> None:
        self._values.pop(name, None)


__all__ = [
    "InMemorySecretStore",
    "SERVICE_NAME",
    "SecretStore",
    "SecretStoreError",
    "SecretStoreProtocol",
]
