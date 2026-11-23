"""Encrypt small secrets with the current Windows user's DPAPI key."""

from __future__ import annotations

import ctypes
from ctypes import wintypes


class SecretError(RuntimeError):
    """Raised when the password cannot be encrypted or decrypted."""


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


_crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_crypt32.CryptProtectData.argtypes = [
    ctypes.POINTER(_DATA_BLOB),
    wintypes.LPCWSTR,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(_DATA_BLOB),
]
_crypt32.CryptProtectData.restype = wintypes.BOOL
_crypt32.CryptUnprotectData.argtypes = [
    ctypes.POINTER(_DATA_BLOB),
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(_DATA_BLOB),
]
_crypt32.CryptUnprotectData.restype = wintypes.BOOL
_kernel32.LocalFree.argtypes = [ctypes.c_void_p]
_kernel32.LocalFree.restype = ctypes.c_void_p


def _blob(data: bytes) -> _DATA_BLOB:
    buffer = ctypes.create_string_buffer(data)
    blob = _DATA_BLOB()
    blob.cbData = len(data)
    blob.pbData = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))
    blob._buffer = buffer
    return blob


def _copy_out(blob: _DATA_BLOB) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        _kernel32.LocalFree(ctypes.cast(blob.pbData, ctypes.c_void_p))


def protect(data: bytes) -> bytes:
    if not data:
        raise SecretError("没有可以加密的内容。")
    incoming = _blob(data)
    outgoing = _DATA_BLOB()
    ok = _crypt32.CryptProtectData(
        ctypes.byref(incoming),
        "LinuxJobDesk",
        None,
        None,
        None,
        0,
        ctypes.byref(outgoing),
    )
    if not ok:
        raise SecretError(f"Windows 没能加密密码：{ctypes.WinError(ctypes.get_last_error())}")
    return _copy_out(outgoing)


def unprotect(data: bytes) -> bytes:
    if not data:
        raise SecretError("读不出已保存的密码，请在账号里重新填写。")
    incoming = _blob(data)
    outgoing = _DATA_BLOB()
    ok = _crypt32.CryptUnprotectData(
        ctypes.byref(incoming),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(outgoing),
    )
    if not ok:
        raise SecretError("读不出已保存的密码，请在账号里重新填写。")
    return _copy_out(outgoing)
