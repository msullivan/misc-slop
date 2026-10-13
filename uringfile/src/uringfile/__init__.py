"""Asynchronous file I/O on io_uring, with anyio's file API.

Works under asyncio and Trio through anyio. Pure Python, Linux only::

    from uringfile import open_file

    async with await open_file("data.bin", "rb") as f:
        header = await f.read(16)
"""

from __future__ import annotations

from ._file import AsyncFile, open_file, wrap_file
from ._path import Path

__all__ = ["AsyncFile", "Path", "available", "open_file", "wrap_file"]
__version__ = "0.1.0"


def available() -> bool:
    """Return whether io_uring can be used in this process.

    False on kernels older than 5.6, and wherever io_uring is turned off: the
    ``kernel.io_uring_disabled`` sysctl, or a seccomp filter such as the
    default one in Docker.
    """
    from ._driver import Driver
    from ._uring import OP_CLOSE, OP_OPENAT, OP_READ, OP_WRITE

    try:
        driver = Driver()
    except OSError:
        return False
    try:
        return {OP_OPENAT, OP_CLOSE, OP_READ, OP_WRITE} <= driver.supported
    finally:
        driver.close()
