import json
import os

import pytest
from macro_pit import fileio


def sharing_error(code):
    error = PermissionError("file temporarily unavailable")
    error.winerror = code
    return error


@pytest.mark.parametrize("code", [5, 32, 33])
def test_transient_windows_error_preserves_old_file_until_replace(tmp_path, monkeypatch, code):
    path = tmp_path / "state.json"
    path.write_text('{"old":true}')
    original = path.read_bytes()
    replace = fileio.os.replace
    calls = []
    delays = []
    def flaky(source, target):
        calls.append(source)
        assert path.read_bytes() == original
        assert json.loads(source.read_text()) == {"new": True}
        if len(calls) < 3:
            raise sharing_error(code)
        replace(source, target)
    monkeypatch.setattr(fileio.os, "replace", flaky)
    monkeypatch.setattr(fileio.time, "sleep", delays.append)
    fileio.atomic_write_text(path, '{"new":true}')
    assert json.loads(path.read_text()) == {"new": True}
    assert delays == [0.05, 0.1]
    assert not list(tmp_path.glob("*.tmp"))


def test_persistent_denial_retains_old_state_and_separate_recovery_files(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text("old")
    calls = []
    delays = []
    def denied(source, target):
        calls.append(source)
        raise sharing_error(5)
    monkeypatch.setattr(fileio.os, "replace", denied)
    monkeypatch.setattr(fileio.time, "sleep", delays.append)
    for content in ["first", "second"]:
        with pytest.raises(PermissionError):
            fileio.atomic_write_text(path, content)
    assert path.read_text() == "old"
    assert len(calls) == 16 and len(delays) == 14
    assert sorted(p.read_text() for p in tmp_path.glob("*.tmp")) == ["first", "second"]


def test_other_io_failures_do_not_retry(tmp_path, monkeypatch):
    def disk_full(source, target):
        raise OSError(28, "disk full")
    monkeypatch.setattr(fileio.os, "replace", disk_full)
    monkeypatch.setattr(fileio.time, "sleep", lambda _: pytest.fail("must not retry"))
    with pytest.raises(OSError, match="disk full"):
        fileio.atomic_write_text(tmp_path / "state.json", "complete")


def test_search_checkpoint_uses_same_retry_path(tmp_path, monkeypatch):
    from macro_pit.nbs_search import _save_state
    replace = fileio.os.replace
    attempts = []
    def flaky(source, target):
        attempts.append(target)
        if len(attempts) == 1:
            raise sharing_error(5)
        replace(source, target)
    monkeypatch.setattr(fileio.os, "replace", flaky)
    monkeypatch.setattr(fileio.time, "sleep", lambda _: None)
    path = tmp_path / "search.json"
    state = {"next_page": 9, "complete": False}
    _save_state(path, state)
    assert json.loads(path.read_text()) == state
    assert len(attempts) == 2


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing semantics")
def test_real_windows_reader_without_delete_sharing(tmp_path, monkeypatch):
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    path = tmp_path / "state.json"
    path.write_text("old")
    handle = kernel.CreateFileW(str(path), 0x80000000, 3, None, 3, 0x80, None)
    assert handle != ctypes.c_void_p(-1).value
    released = []
    def release_reader(seconds):
        assert path.read_text() == "old"
        assert kernel.CloseHandle(handle)
        released.append(seconds)
    monkeypatch.setattr(fileio.time, "sleep", release_reader)
    try:
        fileio.atomic_write_text(path, "new")
    finally:
        if not released:
            kernel.CloseHandle(handle)
    assert released == [0.05]
    assert path.read_text() == "new"
