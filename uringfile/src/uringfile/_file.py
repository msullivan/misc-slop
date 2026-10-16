"""The public file API: :func:`open_file`, :func:`wrap_file`, :class:`AsyncFile`.

This mirrors :func:`anyio.open_file`, :func:`anyio.wrap_file` and
:class:`anyio.AsyncFile`, with the I/O done through io_uring instead of
worker threads.
"""

from __future__ import annotations

import errno
import io
import os
import select
import stat
import sys
import warnings
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from os import PathLike
from typing import IO, TYPE_CHECKING, Any, AnyStr, Generic, TypeVar, overload

from anyio import CancelScope, Event, create_task_group, to_thread
from anyio.abc import AsyncResource
from anyio.lowlevel import checkpoint_if_cancelled

from ._driver import Driver, current_driver
from ._io import (
    DEFAULT_BUFFER_SIZE,
    Buffered,
    RawFile,
    Text,
    _unpack_cookie,
    resolve_text_params,
)
from ._uring import stat_cached

if TYPE_CHECKING:
    from _typeshed import OpenBinaryMode, OpenTextMode, ReadableBuffer, WriteableBuffer

__all__ = ["AsyncFile", "open_file", "wrap_file"]

_T = TypeVar("_T")


class AsyncFile(AsyncResource, Generic[AnyStr]):
    """An asynchronous file object backed by io_uring.

    Obtained from :func:`open_file`, :func:`wrap_file` or
    :meth:`uringfile.Path.open`; not meant to be constructed directly.

    The interface is that of :class:`anyio.AsyncFile`: ``read``, ``read1``,
    ``readline``, ``readlines``, ``readinto``, ``readinto1``, ``write``,
    ``writelines``, ``truncate``, ``seek``, ``tell`` and ``flush`` are
    coroutines with the semantics of the corresponding :mod:`io` methods, and
    the object is an async context manager and an async iterator over lines::

        async with await open_file(path) as f:
            async for line in f:
                ...

    In addition there are ``peek`` (binary files) and ``fsync``.

    Calls from several tasks are serialized, as they are for the built-in
    file objects under threads.

    Checkpoints: a call answered entirely from the buffer, as most
    ``readline`` and small ``read`` and ``write`` calls are, returns at once.
    One that reaches the kernel checks for cancellation first. If the kernel
    then has to make it wait, other tasks run meanwhile; if the kernel
    answers on the spot, as it does for cached data, the call yields to the
    event loop only when the task has gone half a millisecond without doing
    so. A loop over a file therefore never starves the rest of the program,
    but does not pay for a trip through the event loop on every call.

    Cancellation is passed on to the kernel, which makes blocked reads,
    writes and FIFO opens cancellable where a worker thread would be stuck.
    A cancelled call leaves the file consistent: bytes that had already
    been read are kept for the next read, and bytes that had already been
    written are not written again.
    """

    def __init__(self, impl: Any, wrapped: Any = None) -> None:
        self._impl = impl
        self._wrapped = wrapped
        raw = impl
        while not isinstance(raw, RawFile):
            raw = raw.buffer if isinstance(raw, Text) else raw.raw
        self._raw: RawFile = raw
        # A minimal mutex. Uncontended, it costs one attribute test.
        self._busy = False
        self._waiters: deque[Event] = deque()

    def __repr__(self) -> str:
        if self.closed:
            return f"<uringfile.AsyncFile name={self.name!r} [closed]>"
        extra = f" encoding={self.encoding!r}" if isinstance(self._impl, Text) else ""
        return f"<uringfile.AsyncFile name={self.name!r} mode={self.mode!r}{extra}>"

    def __del__(self) -> None:
        raw = getattr(self, "_raw", None)
        if raw is None or raw._fd < 0:
            return
        message = f"unclosed file {self!r}"
        # Like the built-in file objects, don't lose buffered writes.
        impl = self._impl
        buffered = impl.buffer if isinstance(impl, Text) else impl
        try:
            if isinstance(buffered, Buffered):
                buffered.flush_now()
        except Exception:
            pass
        owned = raw._closefd or self._wrapped is not None
        try:
            raw.close_now()
        except Exception:
            pass
        if owned:
            # Last, so that warnings-as-errors cannot stop the cleanup.
            warnings.warn(message, ResourceWarning, stacklevel=2, source=self)

    # -- mutual exclusion ---------------------------------------------

    async def _turn(self) -> None:
        """Wait for the operation in progress on this file to finish."""
        event = Event()
        self._waiters.append(event)
        try:
            await event.wait()
        except BaseException:
            if event.is_set():
                self._release()  # we had been handed the file; pass it on
            else:
                self._waiters.remove(event)
            raise

    def _release(self) -> None:
        if self._waiters:
            self._waiters.popleft().set()  # hand over directly; stays busy
        else:
            self._busy = False

    async def _locked(self, fn: Callable[..., Awaitable[_T]], *args: Any) -> _T:
        """Run ``fn(*args)`` with the file to ourselves.

        ``read``, ``readline`` and ``write`` do this inline instead: the
        extra coroutine costs about 0.3 µs a call, a fifth of a ``readline``
        answered from the buffer.
        """
        if self._busy:
            await self._turn()
        else:
            self._busy = True
        try:
            return await fn(*args)
        finally:
            self._release()

    # -- synchronous attributes ---------------------------------------

    @property
    def wrapped(self) -> IO[AnyStr]:
        """The file object given to :func:`wrap_file`.

        Files from :func:`open_file` have no synchronous file object behind
        them, so for those this raises :exc:`AttributeError`.
        """
        if self._wrapped is None:
            raise AttributeError("this file was not created by wrap_file()")
        return self._wrapped

    @property
    def name(self) -> Any:
        """The path or descriptor the file was opened with."""
        return self._impl.name

    @property
    def mode(self) -> str:
        return self._impl.mode

    @property
    def closed(self) -> bool:
        return self._raw._fd < 0

    @property
    def encoding(self) -> str:
        return self._text().encoding

    @property
    def errors(self) -> str:
        return self._text().errors

    @property
    def newlines(self) -> str | tuple[str, ...] | None:
        return self._text().newlines

    @property
    def line_buffering(self) -> bool:
        return self._text().line_buffering

    def _text(self) -> Text:
        if not isinstance(self._impl, Text):
            raise AttributeError("not a text file")  # noqa: TRY004 (hasattr must work)
        return self._impl

    def fileno(self) -> int:
        return self._raw.fileno()

    def isatty(self) -> bool:
        return self._raw.isatty()

    def readable(self) -> bool:
        return self._raw.readable()

    def writable(self) -> bool:
        return self._raw.writable()

    def seekable(self) -> bool:
        return self._raw.seekable()

    # -- closing ------------------------------------------------------

    async def aclose(self) -> None:
        """Flush and close the file.

        The descriptor is always closed, cancelled or not. For a regular
        file the flush is too: closing never loses what was written. For
        a pipe, FIFO or terminal, which can stall a flush indefinitely,
        cancellation closes at once and drops what was still buffered.
        """
        if self._busy:
            try:
                await self._turn()
            except BaseException:
                # Cancelled while waiting for another task to finish with
                # the file. Close it under that task.
                self._raw.close_now()
                if self._wrapped is not None:
                    self._wrapped.close()
                raise
        else:
            self._busy = True
        try:
            try:
                await self._impl.close()
            finally:
                wrapped = self._wrapped
                if wrapped is not None and not wrapped.closed:
                    with CancelScope(shield=True):
                        await to_thread.run_sync(wrapped.close)
        finally:
            self._release()
        # Closed, whatever happened. If that was done under a cancellation
        # that the shielded parts held off, let it through now.
        await checkpoint_if_cancelled()

    # -- reading ------------------------------------------------------

    async def __aiter__(self) -> AsyncIterator[AnyStr]:
        while True:
            line = await self.readline()
            if line:
                yield line
            else:
                break

    async def read(self, size: int | None = -1) -> AnyStr:
        # _locked(), written out for speed; see there.
        if self._busy:
            await self._turn()
        else:
            self._busy = True
        try:
            return await self._impl.read(size)
        finally:
            self._release()

    async def read1(self: AsyncFile[bytes], size: int = -1) -> bytes:
        return await self._locked(self._binary("read1").read1, size)

    async def peek(self: AsyncFile[bytes], size: int = 0) -> bytes:
        return await self._locked(self._binary("peek").peek, size)

    async def readline(self, size: int | None = -1) -> AnyStr:
        # _locked(), written out for speed; see there.
        if self._busy:
            await self._turn()
        else:
            self._busy = True
        try:
            return await self._impl.readline(size)
        finally:
            self._release()

    async def readlines(self, hint: int | None = -1) -> list[AnyStr]:
        return await self._locked(self._readlines, hint)

    async def _readlines(self, hint: int | None) -> list[AnyStr]:
        readline = self._impl.readline
        lines: list[AnyStr] = []
        total = 0
        while True:
            line = await readline()
            if not line:
                return lines
            lines.append(line)
            total += len(line)
            if hint is not None and 0 < hint < total:  # as the C io module counts
                return lines

    async def readinto(self: AsyncFile[bytes], b: WriteableBuffer) -> int:
        return await self._locked(self._binary("readinto").readinto, b)

    async def readinto1(self: AsyncFile[bytes], b: WriteableBuffer) -> int:
        return await self._locked(self._binary("readinto1").readinto1, b)

    def _binary(self, method: str) -> Any:
        impl = self._impl
        if not hasattr(impl, method):
            raise io.UnsupportedOperation(method)
        return impl

    # -- writing ------------------------------------------------------

    @overload
    async def write(self: AsyncFile[bytes], b: ReadableBuffer) -> int: ...

    @overload
    async def write(self: AsyncFile[str], b: str) -> int: ...

    async def write(self, b: ReadableBuffer | str) -> int:
        # _locked(), written out for speed; see there.
        if self._busy:
            await self._turn()
        else:
            self._busy = True
        try:
            return await self._impl.write(b)
        finally:
            self._release()

    @overload
    async def writelines(self: AsyncFile[bytes], lines: Iterable[ReadableBuffer]) -> None: ...

    @overload
    async def writelines(self: AsyncFile[str], lines: Iterable[str]) -> None: ...

    async def writelines(self, lines: Iterable[ReadableBuffer] | Iterable[str]) -> None:
        return await self._locked(self._writelines, lines)

    async def _writelines(self, lines: Iterable[Any]) -> None:
        write = self._impl.write
        for line in lines:
            await write(line)

    async def truncate(self, size: int | None = None) -> int:
        return await self._locked(self._impl.truncate, size)

    async def flush(self) -> None:
        """Pass buffered writes to the kernel. (Not a sync to disk; see :meth:`fsync`.)"""
        return await self._locked(self._impl.flush)

    async def fsync(self, *, datasync: bool = False) -> None:
        """Flush, then have the kernel commit the file to storage.

        With ``datasync`` this is ``fdatasync(2)``: metadata not needed to
        read the data back is not forced out.
        """
        return await self._locked(self._impl.fsync, datasync)

    # -- position -----------------------------------------------------

    async def seek(self, offset: int, whence: int | None = os.SEEK_SET) -> int:
        return await self._locked(
            self._impl.seek, offset, os.SEEK_SET if whence is None else whence
        )

    async def tell(self) -> int:
        return await self._locked(self._impl.tell)


# ---------------------------------------------------------------------------
# open_file
# ---------------------------------------------------------------------------


def _parse_mode(mode: str) -> tuple[bool, bool, bool, bool, bool, bool]:
    """Return (creating, reading, writing, appending, updating, binary)."""
    if not isinstance(mode, str):
        raise TypeError(f"invalid mode: {mode!r}")
    modes = set(mode)
    if modes - set("axrwb+t") or len(mode) > len(modes):
        raise ValueError(f"invalid mode: {mode!r}")
    creating, reading, writing, appending = (c in modes for c in "xrwa")
    updating, text, binary = "+" in modes, "t" in modes, "b" in modes
    if text and binary:
        raise ValueError("can't have text and binary mode at once")
    if creating + reading + writing + appending != 1:
        raise ValueError("must have exactly one of create/read/write/append mode")
    return creating, reading, writing, appending, updating, binary


def _buffer_size(buffering: int, blksize: int) -> int:
    """The buffer size open() would pick on this version of Python."""
    if buffering > 1:
        return buffering
    if sys.version_info >= (3, 14):
        return max(min(blksize, 8192 * 1024), DEFAULT_BUFFER_SIZE)
    return blksize if blksize > 1 else DEFAULT_BUFFER_SIZE


def _stack(
    raw: RawFile,
    *,
    binary: bool,
    buffer_size: int,
    line_buffering: bool = False,
    encoding: str | None = None,
    errors: str | None = None,
    newline: str | None = None,
    mode: str | None = None,
) -> Any:
    """Build the layers above ``raw``. ``buffer_size`` 0 means unbuffered."""
    if not buffer_size:
        return raw
    if raw._readable and raw._writable and not raw.seekable():
        raise io.UnsupportedOperation("File or stream is not seekable.")
    buffered = Buffered(raw, buffer_size)
    if binary:
        return buffered
    encoding, errors = resolve_text_params(encoding, errors)
    return Text(buffered, encoding, errors, newline, line_buffering, mode)


async def _wait_for_fifo_writer(driver: Driver, fd: int, path: bytes, flags: int) -> None:
    """Give the read end of a FIFO the semantics open(2) would have.

    open(2) on a FIFO waits for the other end. The ring's open does not: it
    is tried as if with ``O_NONBLOCK`` first, and for a FIFO that changes
    the meaning. The read end opens at once whether or not there is a
    writer, and without one the first read reports end of file.

    So, having got ``fd`` that way, wait here until a writer has shown up.
    Only another, blocking open can wait for exactly that. But a writer may
    already have come and gone, since our first open is what let it in, and
    the second open would then wait for the next one; that case shows up on
    ``fd`` itself as data or a hangup. Whichever happens first settles it,
    and ``fd``, which was open throughout so that no writer ever saw the
    FIFO without a reader, is the descriptor to use.
    """

    failure: OSError | None = None

    async def reopen() -> None:
        nonlocal failure
        try:
            second = await driver.openat(path, flags, blocking=True)
        except FileNotFoundError:
            pass  # unlinked meanwhile: nobody else can turn up either
        except OSError as exc:
            failure = exc  # raised below, not from in here as a group
        else:
            with CancelScope(shield=True):
                await driver.close_fd(second)
        tg.cancel_scope.cancel()

    async with create_task_group() as tg:
        tg.start_soon(reopen)
        await driver.poll(fd, select.POLLIN)
        tg.cancel_scope.cancel()
    if failure is not None:
        raise failure


@overload
async def open_file(
    file: str | bytes | PathLike[str] | PathLike[bytes] | int,
    mode: OpenBinaryMode,
    buffering: int = ...,
    encoding: str | None = ...,
    errors: str | None = ...,
    newline: str | None = ...,
    closefd: bool = ...,
    opener: Callable[[str, int], int] | None = ...,
) -> AsyncFile[bytes]: ...


@overload
async def open_file(
    file: str | bytes | PathLike[str] | PathLike[bytes] | int,
    mode: OpenTextMode = ...,
    buffering: int = ...,
    encoding: str | None = ...,
    errors: str | None = ...,
    newline: str | None = ...,
    closefd: bool = ...,
    opener: Callable[[str, int], int] | None = ...,
) -> AsyncFile[str]: ...


@overload
async def open_file(
    file: str | bytes | PathLike[str] | PathLike[bytes] | int,
    mode: str,
    buffering: int = ...,
    encoding: str | None = ...,
    errors: str | None = ...,
    newline: str | None = ...,
    closefd: bool = ...,
    opener: Callable[[str, int], int] | None = ...,
) -> AsyncFile[Any]: ...


async def open_file(
    file: str | bytes | PathLike[str] | PathLike[bytes] | int,
    mode: str = "r",
    buffering: int = -1,
    encoding: str | None = None,
    errors: str | None = None,
    newline: str | None = None,
    closefd: bool = True,
    opener: Callable[[str, int], int] | None = None,
) -> AsyncFile[Any]:
    """Open a file asynchronously.

    The arguments are exactly those of the builtin :func:`open`, and so is
    their meaning. A custom ``opener`` is run in a worker thread.

    :return: an asynchronous file object
    """
    creating, reading, writing, appending, updating, binary = _parse_mode(mode)
    if binary:
        if encoding is not None:
            raise ValueError("binary mode doesn't take an encoding argument")
        if errors is not None:
            raise ValueError("binary mode doesn't take an errors argument")
        if newline is not None:
            raise ValueError("binary mode doesn't take a newline argument")
        if buffering == 1:
            warnings.warn(
                "line buffering (buffering=1) isn't supported in binary mode, "
                "the default buffer size will be used",
                RuntimeWarning,
                stacklevel=2,
            )
    else:
        if buffering == 0:
            raise ValueError("can't have unbuffered text I/O")
        if newline not in (None, "", "\n", "\r", "\r\n"):
            raise ValueError(f"illegal newline value: {newline!r}")
        # Fail on a bad encoding before touching the filesystem.
        encoding, errors = resolve_text_params(encoding, errors)

    readable = reading or updating
    writable = not reading or updating
    flags = os.O_RDWR if readable and writable else os.O_RDONLY if readable else os.O_WRONLY
    if creating:
        flags |= os.O_EXCL | os.O_CREAT
    elif writing:
        flags |= os.O_CREAT | os.O_TRUNC
    elif appending:
        flags |= os.O_APPEND | os.O_CREAT
    flags |= os.O_CLOEXEC

    driver = current_driver()
    if isinstance(file, int):
        if file < 0:
            raise ValueError("negative file descriptor")
        if file > 0x7FFF_FFFF:  # what open() says of an int that is no descriptor
            raise TypeError("expected str, bytes or os.PathLike object, not int")
        fd = file
        owned = False  # even with closefd, not ours to close until we return
    else:
        if not closefd:
            raise ValueError("Cannot use closefd=False with file name")
        path = os.fspath(file)
        if opener is not None:
            # (An opener gets bytes for a bytes path; typeshed's open() does
            # not say so either.)
            fd = await to_thread.run_sync(opener, path, flags)  # type: ignore[arg-type]
            if not isinstance(fd, int):
                raise TypeError("expected integer from opener")
            if fd < 0:
                raise ValueError(f"opener returned {fd}")
        else:
            encoded = os.fsencode(path)
            if b"\0" in encoded:
                raise ValueError("embedded null byte")
            try:
                fd = await driver.openat(encoded, flags)
            except OSError as exc:
                # What a non-blocking open says about a FIFO nobody is
                # reading. open(2) would wait for a reader; so do we.
                if exc.errno != errno.ENXIO:
                    raise
                fd = await driver.openat(encoded, flags, blocking=True)
        owned = True

    try:
        st_mode, st_size, st_blksize = stat_cached(fd)
        if stat.S_ISFIFO(st_mode) and owned and opener is None and not writable:
            await _wait_for_fifo_writer(driver, fd, encoded, flags)
        if stat.S_ISDIR(st_mode):
            raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), file)
        if appending:
            # For the benefit of tell(); the kernel appends regardless.
            try:
                os.lseek(fd, 0, os.SEEK_END)
            except OSError:
                pass
        raw = RawFile(
            fd,
            file,
            readable=readable,
            writable=writable,
            created=creating,
            appending=appending,
            truncated=writing,
            closefd=closefd,
            regular=stat.S_ISREG(st_mode),
            # Only trust the size if we know we are at the start.
            size_hint=(
                st_size
                if owned and opener is None and stat.S_ISREG(st_mode) and not appending
                else None
            ),
        )
        line_buffering = False
        if buffering == 1 or (buffering < 0 and stat.S_ISCHR(st_mode) and os.isatty(fd)):
            line_buffering = not binary
            buffering = -1
        impl = _stack(
            raw,
            binary=binary,
            buffer_size=0 if buffering == 0 else _buffer_size(buffering, st_blksize),
            line_buffering=line_buffering,
            encoding=encoding,
            errors=errors,
            newline=newline,
            mode=mode,
        )
    except BaseException:
        if owned:
            with CancelScope(shield=True):
                await driver.close_fd(fd)
        raise
    return AsyncFile(impl)


# ---------------------------------------------------------------------------
# wrap_file
# ---------------------------------------------------------------------------


def wrap_file(file: IO[AnyStr], *, newline: str | None = None) -> AsyncFile[AnyStr]:
    """Take over an open file object and return an asynchronous file for it.

    The file object must be backed by a real file descriptor (for anything
    else, such as ``io.BytesIO``, use :func:`anyio.wrap_file`). Pending
    writes are flushed and the new file continues from the position the
    old one was at. From then on the original must only be used through
    the returned object, whose ``aclose()`` closes it.

    Two things cannot be recovered from an existing file object:

    * input it had already buffered from a pipe or terminal, which is lost;
    * the ``newline`` argument a text file was opened with, which you can
      pass again here if it was not the default.

    :param file: an open file object with a working ``fileno()``
    :param newline: newline mode for text files, as for :func:`open`
    :return: an asynchronous file object
    """
    try:
        fd = file.fileno()
    except (AttributeError, OSError) as exc:  # io.UnsupportedOperation is an OSError
        raise TypeError(
            f"{type(file).__name__} object has no file descriptor; "
            "use anyio.wrap_file() for file-like objects that are not real files"
        ) from exc
    readable, writable = file.readable(), file.writable()
    if writable:
        file.flush()
    mode = getattr(file, "mode", None)
    raw = RawFile(
        fd,
        getattr(file, "name", fd),
        readable=readable,
        writable=writable,
        appending=isinstance(mode, str) and "a" in mode,
        created=isinstance(mode, str) and "x" in mode,
        truncated=isinstance(mode, str) and "w" in mode,
        closefd=False,
        regular=stat.S_ISREG(stat_cached(fd)[0]),
    )
    binary = not (isinstance(file, io.TextIOBase) or hasattr(file, "encoding"))
    unbuffered = isinstance(file, io.RawIOBase)
    try:
        cookie = file.tell() if raw.seekable() else None
    except OSError:  # e.g. tell() disabled by iterating over a text file
        cookie = None

    impl = _stack(
        raw,
        binary=binary,
        buffer_size=0 if unbuffered else DEFAULT_BUFFER_SIZE,
        line_buffering=bool(getattr(file, "line_buffering", False)),
        encoding=getattr(file, "encoding", None),
        errors=getattr(file, "errors", None),
        newline=newline,
        mode=mode if isinstance(mode, str) else None,
    )
    if cookie is not None:
        # The descriptor's position is wherever the old object's read-ahead
        # left it. Move it to where the old object logically was.
        if isinstance(impl, Text):
            start, flags, feed, skip, need_eof = _unpack_cookie(cookie)
            raw._seek(start)
            impl._restore_decoder(cookie, flags, skip)
            if skip:
                # A few bytes the old object has just read; they are cached.
                chunk = os.pread(fd, feed, start)
                raw._seek(start + len(chunk))
                impl._restore_chunk(flags, skip, need_eof, chunk)
            impl._reset_encoder(cookie == 0)
        else:
            raw._seek(cookie)
    return AsyncFile(impl, wrapped=file)
