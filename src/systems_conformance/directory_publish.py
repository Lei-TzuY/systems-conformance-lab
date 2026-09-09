from __future__ import annotations

import ctypes
import errno
import os
import sys
from pathlib import Path

_AT_FDCWD = -100
_RENAME_NOREPLACE = 1
_RENAME_EXCL = 0x00000004
_ERROR_ALREADY_EXISTS = 183
_ERROR_FILE_EXISTS = 80


def _raise_publication_error(error_number: int, destination: Path) -> None:
    if error_number in {errno.EEXIST, errno.ENOTEMPTY, _ERROR_ALREADY_EXISTS, _ERROR_FILE_EXISTS}:
        raise FileExistsError(
            error_number,
            f"destination already exists: {destination}",
            str(destination),
        )
    raise OSError(error_number, os.strerror(error_number), str(destination))


def publish_directory_no_replace(staging: Path, destination: Path) -> None:
    """Atomically publish one directory without replacing an existing entry.

    The primitive is deliberately fail-closed on platforms where this project
    does not have a verified atomic no-replace directory rename operation.
    """

    staging = Path(staging)
    destination = Path(destination)

    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise NotImplementedError("atomic no-replace directory publication requires renameat2")
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        result = renameat2(
            _AT_FDCWD,
            os.fsencode(staging),
            _AT_FDCWD,
            os.fsencode(destination),
            _RENAME_NOREPLACE,
        )
        if result != 0:
            _raise_publication_error(ctypes.get_errno(), destination)
        return

    if sys.platform == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        renamex_np = getattr(libc, "renamex_np", None)
        if renamex_np is None:
            raise NotImplementedError("atomic no-replace directory publication requires renamex_np")
        renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex_np.restype = ctypes.c_int
        result = renamex_np(
            os.fsencode(staging),
            os.fsencode(destination),
            _RENAME_EXCL,
        )
        if result != 0:
            _raise_publication_error(ctypes.get_errno(), destination)
        return

    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        move_file_ex = kernel32.MoveFileExW
        move_file_ex.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        move_file_ex.restype = ctypes.c_int
        if not move_file_ex(str(staging), str(destination), 0):
            error_number = ctypes.get_last_error()
            if error_number in {_ERROR_ALREADY_EXISTS, _ERROR_FILE_EXISTS}:
                raise FileExistsError(
                    error_number,
                    f"destination already exists: {destination}",
                    str(destination),
                )
            raise ctypes.WinError(error_number)
        return

    raise NotImplementedError(
        f"atomic no-replace directory publication is unsupported on {sys.platform}"
    )
