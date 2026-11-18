"""打开所在文件夹：跨平台命令构造与含空格路径的处理。"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

import pytest

from subtitle_engine.rpc import server as server_module
from subtitle_engine.rpc.errors import INVALID_PARAMS, JsonRpcError


def _fake_os(name: str) -> SimpleNamespace:
    """只替换 server 模块看到的 os，避免污染全局 os.name 影响 pathlib。"""
    return SimpleNamespace(name=name, fspath=os.fspath)


class _PopenSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def __call__(self, args: Any, **kwargs: Any) -> _PopenSpy:
        self.calls.append((args, kwargs))
        return self


@pytest.fixture
def popen_spy(monkeypatch) -> _PopenSpy:
    spy = _PopenSpy()
    monkeypatch.setattr(server_module.subprocess, "Popen", spy)
    return spy


@pytest.fixture
def spaced_file(tmp_path):
    folder = tmp_path / "Die Discounter Staffel 1"
    folder.mkdir()
    target = folder / "Die Discounter S01E01.srt"
    target.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    return target


@pytest.fixture
def spaced_folder(tmp_path):
    folder = tmp_path / "Die Discounter Staffel 1"
    folder.mkdir()
    return folder


def test_windows_file_with_spaces_uses_single_command_line(
    monkeypatch, popen_spy, spaced_file
) -> None:
    monkeypatch.setattr(server_module, "os", _fake_os("nt"))
    monkeypatch.setattr(server_module.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

    server_module._reveal_path(str(spaced_file))

    assert len(popen_spy.calls) == 1
    args, kwargs = popen_spy.calls[0]
    expected = f'explorer.exe /select,"{spaced_file}"'
    assert args == expected
    # 关键回归：不能再出现被 subprocess 整体加引号的单参数形式。
    assert args != f'"/select,{spaced_file}"'
    assert not args.startswith('"/select,')
    assert kwargs["creationflags"] == 0x08000000


def test_windows_folder_with_spaces_opens_folder_directly(
    monkeypatch, popen_spy, spaced_folder
) -> None:
    monkeypatch.setattr(server_module, "os", _fake_os("nt"))

    server_module._reveal_path(str(spaced_folder))

    args, _ = popen_spy.calls[0]
    assert args == f'explorer.exe "{spaced_folder}"'
    assert "/select" not in args


def test_macos_reveals_file_without_windows_quoting(
    monkeypatch, popen_spy, spaced_file
) -> None:
    monkeypatch.setattr(server_module, "os", _fake_os("posix"))
    monkeypatch.setattr(server_module, "sys", SimpleNamespace(platform="darwin"))

    server_module._reveal_path(str(spaced_file))

    assert popen_spy.calls[0][0] == ["open", "-R", str(spaced_file)]


def test_linux_opens_containing_folder(monkeypatch, popen_spy, spaced_file) -> None:
    monkeypatch.setattr(server_module, "os", _fake_os("posix"))
    monkeypatch.setattr(server_module, "sys", SimpleNamespace(platform="linux"))

    server_module._reveal_path(str(spaced_file))

    assert popen_spy.calls[0][0] == ["xdg-open", str(spaced_file.parent)]


def test_missing_path_still_raises(monkeypatch, popen_spy, tmp_path) -> None:
    monkeypatch.setattr(server_module, "os", _fake_os("nt"))
    missing = tmp_path / "not there.srt"

    with pytest.raises(JsonRpcError) as excinfo:
        server_module._reveal_path(str(missing))

    assert excinfo.value.code == INVALID_PARAMS
    assert popen_spy.calls == []
