"""An :class:`anyio.Path` whose file contents go through io_uring."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any, overload

import anyio

from ._file import AsyncFile, open_file

if TYPE_CHECKING:
    from _typeshed import OpenBinaryMode, OpenTextMode, ReadableBuffer

__all__ = ["Path"]


class Path(anyio.Path):
    """:class:`anyio.Path`, with file contents read and written via io_uring.

    :meth:`open`, :meth:`read_bytes`, :meth:`read_text`, :meth:`write_bytes`
    and :meth:`write_text` use the ring. Everything else (``stat``,
    ``iterdir``, ``unlink``, ...) is inherited and runs in worker threads as
    in anyio.
    """

    __slots__ = ()

    # The override is deliberately not substitutable: what comes back is this
    # package's AsyncFile, which is not a subclass of anyio's.
    @overload  # type: ignore[override]
    async def open(
        self,
        mode: OpenBinaryMode,
        buffering: int = ...,
        encoding: str | None = ...,
        errors: str | None = ...,
        newline: str | None = ...,
    ) -> AsyncFile[bytes]: ...

    @overload
    async def open(
        self,
        mode: OpenTextMode = ...,
        buffering: int = ...,
        encoding: str | None = ...,
        errors: str | None = ...,
        newline: str | None = ...,
    ) -> AsyncFile[str]: ...

    @overload
    async def open(
        self,
        mode: str,
        buffering: int = ...,
        encoding: str | None = ...,
        errors: str | None = ...,
        newline: str | None = ...,
    ) -> AsyncFile[Any]: ...

    async def open(
        self,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> AsyncFile[Any]:
        return await open_file(self._path, mode, buffering, encoding, errors, newline)

    async def read_bytes(self) -> bytes:
        async with await open_file(self._path, "rb") as f:
            return await f.read()

    if sys.version_info >= (3, 13):

        async def read_text(
            self,
            encoding: str | None = None,
            errors: str | None = None,
            newline: str | None = None,
        ) -> str:
            async with await open_file(
                self._path, "r", encoding=encoding, errors=errors, newline=newline
            ) as f:
                return await f.read()

    else:

        async def read_text(  # type: ignore[misc]
            self, encoding: str | None = None, errors: str | None = None
        ) -> str:
            async with await open_file(self._path, "r", encoding=encoding, errors=errors) as f:
                return await f.read()

    async def write_bytes(self, data: ReadableBuffer) -> int:
        # As pathlib does, take the size up front: this also rejects str.
        view = memoryview(data)
        async with await open_file(self._path, "wb") as f:
            return await f.write(view)

    async def write_text(
        self,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        if not isinstance(data, str):
            raise TypeError(f"data must be str, not {data.__class__.__name__}")
        async with await open_file(
            self._path, "w", encoding=encoding, errors=errors, newline=newline
        ) as f:
            return await f.write(data)
