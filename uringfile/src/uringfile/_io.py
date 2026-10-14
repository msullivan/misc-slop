"""Async counterparts of the three layers of Python's :mod:`io` stack.

=================  ==========================  ==============================
this module        standard library            does
=================  ==========================  ==============================
:class:`RawFile`   :class:`io.FileIO`          one io_uring operation per call
:class:`Buffered`  :class:`io.BufferedRandom`  read-ahead and write-behind
:class:`Text`      :class:`io.TextIOWrapper`   decoding and newline handling
=================  ==========================  ==============================

They are internal: :class:`uringfile.AsyncFile` wraps whichever one sits on
top, adds mutual exclusion, and is what callers see.

Two properties hold throughout.

**Cancellation never loses or duplicates data.** A cancelled call leaves the
stream where it was before the call, or, if the kernel got as far as moving
bytes before it could be stopped, with those bytes accounted for: read bytes
are kept for the next read, written bytes are dropped from the write buffer.
The one thing a cancelled ``write()`` cannot promise is whether its data was
taken; see :meth:`Buffered.write`.

**A buffer handed to the kernel is never resized or reused until the kernel
has answered.** Where an operation is abandoned mid-flight (which takes more
than an ordinary cancellation), its buffer is dropped rather than recycled.
"""

from __future__ import annotations

import asyncio
import codecs
import errno
import io
import os
import stat
import sys
from collections.abc import Callable
from os import SEEK_CUR, SEEK_END, SEEK_SET
from typing import Any

from anyio import CancelScope

from ._driver import MAX_RW, cancel_pending, current_driver
from ._uring import stat_cached

DEFAULT_BUFFER_SIZE = io.DEFAULT_BUFFER_SIZE
# When the built-in buffered writer bypasses its buffer changed in 3.13.
_WRITE_THROUGH_WHEN_EQUAL = sys.version_info >= (3, 13)
_NO_BUFFER = b""  # stands in for a read buffer that has not been allocated


def _closed() -> ValueError:
    return ValueError("I/O operation on closed file")


def _writable_view(b: Any) -> memoryview:
    view = memoryview(b)
    if view.readonly:
        raise TypeError(
            f"readinto() argument must be read-write bytes-like object, not {type(b).__name__}"
        )
    return view.cast("B")


# ---------------------------------------------------------------------------
# Raw
# ---------------------------------------------------------------------------


class RawFile:
    """An open file descriptor. Every read and write is one ring operation.

    The kernel owns the file position (operations are submitted with offset
    -1, "use and advance the position, as read(2) would"), so the descriptor
    behaves the same whether it is a regular file, a pipe or a terminal, and
    stays coherent with anything else that shares it.
    """

    def __init__(
        self,
        fd: int,
        name: Any,
        *,
        readable: bool,
        writable: bool,
        created: bool = False,
        appending: bool = False,
        closefd: bool = True,
        size_hint: int | None = None,
        regular: bool = False,
    ) -> None:
        self._fd = fd
        self.name = name
        #: A regular file: its writes complete in bounded time.
        self._regular = regular
        self._readable = readable
        self._writable = writable
        self._created = created
        self._appending = appending
        self._closefd = closefd
        self._seekable: bool | None = None
        # Bytes that a read delivered after its caller had been cancelled.
        self._stash = b""
        # Bytes left in the file as of open(), valid until the first
        # operation; saves readall() a stat when reading a whole file.
        self._size_hint = size_hint

    # -- introspection ------------------------------------------------

    @property
    def mode(self) -> str:
        if self._created:
            return "xb+" if self._readable else "xb"
        if self._appending:
            return "ab+" if self._readable else "ab"
        if self._readable:
            return "rb+" if self._writable else "rb"
        return "wb"

    @property
    def closed(self) -> bool:
        return self._fd < 0

    @property
    def closefd(self) -> bool:
        return self._closefd

    def fileno(self) -> int:
        if self._fd < 0:
            raise _closed()
        return self._fd

    def isatty(self) -> bool:
        return os.isatty(self.fileno())

    def readable(self) -> bool:
        self.fileno()
        return self._readable

    def writable(self) -> bool:
        self.fileno()
        return self._writable

    def seekable(self) -> bool:
        fd = self.fileno()
        if self._seekable is None:
            try:
                os.lseek(fd, 0, SEEK_CUR)
            except OSError:
                self._seekable = False
            else:
                self._seekable = True
        return self._seekable

    def _check_readable(self) -> None:
        if self._fd < 0:
            raise _closed()
        if not self._readable:
            raise io.UnsupportedOperation("File not open for reading")

    def _check_writable(self) -> None:
        if self._fd < 0:
            raise _closed()
        if not self._writable:
            raise io.UnsupportedOperation("File not open for writing")

    # -- position (lseek does no I/O, so it is called directly) --------

    def _seek(self, pos: int, whence: int = SEEK_SET) -> int:
        fd = self.fileno()
        if self._stash and whence == SEEK_CUR:
            pos -= len(self._stash)
        new = os.lseek(fd, pos, whence)
        self._stash = b""
        self._size_hint = None
        return new

    def _tell(self) -> int:
        return os.lseek(self.fileno(), 0, SEEK_CUR) - len(self._stash)

    async def seek(self, pos: int, whence: int = SEEK_SET) -> int:
        return self._seek(pos, whence)

    async def tell(self) -> int:
        return self._tell()

    # -- reading ------------------------------------------------------

    async def _readinto(self, view: memoryview, late: Callable[[int], object] | None) -> int:
        """One read into ``view``. ``late`` receives the byte count if the
        read completes after its caller was cancelled."""
        self._size_hint = None
        return await current_driver().read(self._fd, view, late)

    async def readinto(self, b: Any) -> int:
        self._check_readable()
        view = _writable_view(b)
        stash = self._stash
        if stash:
            n = min(len(view), len(stash))
            view[:n] = stash[:n]
            self._stash = stash[n:]
            return n

        def late(n: int) -> None:
            self._stash = view[:n].tobytes()

        return await self._readinto(view, late)

    async def read(self, size: int | None = -1) -> bytes:
        if size is None or size < 0:
            return await self.readall()
        buf = bytearray(size)
        n = await self.readinto(buf)
        return memoryview(buf)[:n].tobytes()

    def _remaining(self) -> int:
        """Bytes between the position and the end of a regular file, else 0."""
        mode, size, _ = stat_cached(self._fd)
        if not stat.S_ISREG(mode):
            return 0
        try:
            return max(size - os.lseek(self._fd, 0, SEEK_CUR), 0)
        except OSError:
            return 0

    async def _readall_into(self, chunks: list[bytes | bytearray]) -> None:
        """Read to end of file, appending to ``chunks`` as data arrives.

        ``chunks`` is the caller's so that, if this is interrupted, the
        caller still holds everything that was read.
        """
        hint = self._size_hint
        if hint is None:
            hint = self._remaining()
        # One byte more than expected, so that a file of exactly the expected
        # size is seen to end without growing the buffer.
        bufsize = hint + 1 if hint else DEFAULT_BUFFER_SIZE
        while True:
            buf = bytearray(min(bufsize, MAX_RW))
            view = memoryview(buf)

            def landed(n: int, view: memoryview = view) -> None:
                chunks.append(view[:n].tobytes())

            n = await self._readinto(view, landed)
            if not n:
                return
            if n == len(buf):
                chunks.append(buf)
                bufsize *= 2
            else:
                chunks.append(view[:n].tobytes())
                bufsize = DEFAULT_BUFFER_SIZE

    async def readall(self) -> bytes:
        self._check_readable()
        chunks: list[bytes | bytearray] = [self._stash] if self._stash else []
        self._stash = b""
        try:
            await self._readall_into(chunks)
        except BaseException:
            self._stash = b"".join(chunks)
            raise
        return b"".join(chunks)

    async def readline(self, size: int | None = -1) -> bytes:
        # Unbuffered means unbuffered: there is nowhere to put read-ahead, so
        # like io.RawIOBase.readline this goes a byte at a time.
        self._check_readable()
        limit = -1 if size is None else size
        out = bytearray()
        try:
            while limit < 0 or len(out) < limit:
                b = await self.read(1)
                if not b:
                    break
                out += b
                if b == b"\n":
                    break
        except BaseException:
            self._stash = bytes(out) + self._stash
            raise
        return bytes(out)

    # -- writing ------------------------------------------------------

    async def _write(self, data: Any, late: Callable[[int], object] | None) -> int:
        self._size_hint = None
        return await current_driver().write(self._fd, data, late)

    async def write(self, b: Any) -> int:
        self._check_writable()
        if isinstance(b, str):
            raise TypeError("a bytes-like object is required, not 'str'")
        if self._stash and self.seekable():
            # Bytes that were read but never handed out put the kernel's
            # position ahead of ours. Give them back, so that the write
            # lands where tell() says we are.
            self._seek(0, SEEK_CUR)
        return await self._write(b, None)

    async def flush(self) -> None:
        self.fileno()

    async def truncate(self, size: int | None = None) -> int:
        self._check_writable()
        if size is None:
            size = self._tell()
        elif size < 0:
            raise OSError(errno.EINVAL, os.strerror(errno.EINVAL))
        elif size > 0x7FFF_FFFF_FFFF_FFFF:
            raise OverflowError("Python int too large to convert to C long")
        self._size_hint = None
        await current_driver().ftruncate(self._fd, size)
        return size

    async def fsync(self, datasync: bool = False) -> None:
        await current_driver().fsync(self.fileno(), datasync)

    # -- closing ------------------------------------------------------

    def detach_fd(self) -> int:
        """Give up the descriptor without closing it."""
        fd, self._fd = self._fd, -1
        return fd

    def close_now(self) -> None:
        """Close synchronously. For finalizers and forced teardown."""
        fd = self.detach_fd()
        if fd >= 0 and self._closefd:
            os.close(fd)

    async def close(self) -> None:
        fd = self.detach_fd()
        if fd >= 0 and self._closefd:
            # Once started, a close is seen through: there is nothing useful
            # a caller could do with a descriptor that may or may not be open.
            with CancelScope(shield=True):
                await current_driver().close_fd(fd)


# ---------------------------------------------------------------------------
# Buffered
# ---------------------------------------------------------------------------


class Buffered:
    """Read-ahead and write-behind over a :class:`RawFile`.

    Invariants, with ``unread`` the bytes in the read buffer not yet consumed
    and ``pending`` the bytes in the write buffer:

    * at most one of ``unread`` and ``pending`` is non-empty;
    * logical position = raw position - ``unread`` + ``pending``.
    """

    def __init__(self, raw: RawFile, buffer_size: int = DEFAULT_BUFFER_SIZE) -> None:
        if buffer_size <= 0:
            raise ValueError("invalid buffer size")
        self.raw = raw
        self._size = buffer_size
        # Read buffer: valid bytes are _rbuf[_rpos:_rend].
        self._rbuf: bytearray | bytes = _NO_BUFFER
        self._rpos = 0
        self._rend = 0
        self._wbuf = bytearray()

    # -- introspection (all delegated) --------------------------------

    @property
    def name(self) -> Any:
        return self.raw.name

    @property
    def mode(self) -> str:
        return self.raw.mode

    @property
    def closed(self) -> bool:
        return self.raw._fd < 0

    def fileno(self) -> int:
        return self.raw.fileno()

    def isatty(self) -> bool:
        return self.raw.isatty()

    def readable(self) -> bool:
        return self.raw.readable()

    def writable(self) -> bool:
        return self.raw.writable()

    def seekable(self) -> bool:
        return self.raw.seekable()

    # -- read buffer plumbing -----------------------------------------

    def _take(self, n: int) -> bytes:
        pos = self._rpos
        self._rpos = pos + n
        return memoryview(self._rbuf)[pos : pos + n].tobytes()

    def _pushback(self, data: Any) -> None:
        """Put ``data`` back in front of whatever is still unread."""
        if len(data):
            buf = bytearray(data)
            buf += memoryview(self._rbuf)[self._rpos : self._rend]
            self._rbuf, self._rpos, self._rend = buf, 0, len(buf)

    def _rewind(self) -> None:
        """Drop read-ahead, moving the raw position back to the logical one."""
        unread = self._rend - self._rpos
        if unread:
            self.raw._seek(-unread, SEEK_CUR)
            self._rpos = self._rend = 0

    async def _fill(self) -> int:
        """Refill the empty read buffer with one raw read; 0 means EOF."""
        buf = self._rbuf
        if len(buf) != self._size:
            buf = bytearray(self._size)
        # While the kernel has the buffer it is not ours. If this call is
        # abandoned without an answer, it stays that way and the next fill
        # allocates a new one.
        self._rbuf = _NO_BUFFER
        self._rpos = self._rend = 0

        def landed(n: int) -> None:
            self._rbuf = buf
            self._rend = n

        n = await self.raw._readinto(memoryview(buf), landed)
        landed(n)
        return n

    # -- reading ------------------------------------------------------

    async def read(self, size: int | None = -1) -> bytes:
        if size is None or size < 0:
            return await self._readall()
        raw = self.raw
        raw._check_readable()
        avail = self._rend - self._rpos
        if size <= avail:
            return self._take(size)
        if self._wbuf:
            await self.flush()
            avail = 0

        out = bytearray(size)
        view = memoryview(out)
        got = avail
        if avail:
            view[:avail] = memoryview(self._rbuf)[self._rpos : self._rend]
            self._rpos = self._rend = 0

        def landed(n: int) -> None:
            nonlocal got
            got += n

        try:
            while got < size:
                want = size - got
                if want >= self._size:
                    # Big enough to skip the buffer and read into place.
                    n = await raw._readinto(view[got:], landed)
                    if not n:
                        break
                    got += n
                else:
                    n = await self._fill()
                    if not n:
                        break
                    n = min(n, want)
                    view[got : got + n] = memoryview(self._rbuf)[:n]
                    self._rpos = n
                    got += n
        except BaseException:
            self._pushback(view[:got])
            raise
        return view[:got].tobytes()

    async def _readall(self) -> bytes:
        self.raw._check_readable()
        if self._wbuf:
            await self.flush()
        avail = self._rend - self._rpos
        chunks: list[bytes | bytearray] = [self._take(avail)] if avail else []
        try:
            await self.raw._readall_into(chunks)
        except BaseException:
            self._pushback(b"".join(chunks))
            raise
        return b"".join(chunks)

    async def read1(self, size: int | None = -1) -> bytes:
        """Return up to ``size`` bytes with at most one raw read."""
        raw = self.raw
        raw._check_readable()
        if size is None or size < 0:
            size = self._size
        avail = self._rend - self._rpos
        if avail:
            return self._take(min(avail, size))
        if not size:
            return b""
        if self._wbuf:
            await self.flush()
        if size >= self._size:
            buf = bytearray(size)
            view = memoryview(buf)
            n = await raw._readinto(view, lambda n: self._pushback(view[:n]))
            return view[:n].tobytes()
        n = await self._fill()
        return self._take(min(n, size))

    async def peek(self, size: int = 0) -> bytes:
        """Return buffered bytes without consuming them, reading once if none."""
        self.raw._check_readable()
        if self._rend == self._rpos:
            if self._wbuf:
                await self.flush()
            await self._fill()
        return memoryview(self._rbuf)[self._rpos : self._rend].tobytes()

    async def _readinto(self, b: Any, one: bool) -> int:
        raw = self.raw
        raw._check_readable()
        view = _writable_view(b)
        size = len(view)
        got = min(self._rend - self._rpos, size)
        if got:
            view[:got] = memoryview(self._rbuf)[self._rpos : self._rpos + got]
            self._rpos += got
        if got == size or (one and got):
            return got
        if self._wbuf:
            await self.flush()

        def landed(n: int) -> None:
            nonlocal got
            got += n

        try:
            while got < size:
                want = size - got
                if want >= self._size:
                    n = await raw._readinto(view[got:], landed)
                    if not n:
                        break
                    got += n
                else:
                    n = await self._fill()
                    if not n:
                        break
                    n = min(n, want)
                    view[got : got + n] = memoryview(self._rbuf)[:n]
                    self._rpos = n
                    got += n
                if one:
                    break
        except BaseException:
            # The caller never learns how much of its buffer was filled.
            self._pushback(view[:got])
            raise
        return got

    async def readinto(self, b: Any) -> int:
        return await self._readinto(b, False)

    async def readinto1(self, b: Any) -> int:
        return await self._readinto(b, True)

    async def readline(self, size: int | None = -1) -> bytes:
        self.raw._check_readable()
        limit = -1 if size is None else size
        pos, end = self._rpos, self._rend
        i = self._rbuf.find(b"\n", pos, end)
        if i >= 0:
            n = i + 1 - pos
            return self._take(n if limit < 0 or n < limit else limit)
        if 0 <= limit <= end - pos:
            return self._take(limit)

        if self._wbuf:
            await self.flush()
            pos = end = 0
        chunks = [self._take(end - pos)] if end > pos else []
        total = end - pos
        try:
            while True:
                n = await self._fill()
                if not n:
                    break
                stop = n if limit < 0 else min(n, limit - total)
                i = self._rbuf.find(b"\n", 0, stop)
                if i >= 0:
                    chunks.append(self._take(i + 1))
                    break
                chunks.append(self._take(stop))
                total += stop
                if total == limit:
                    break
        except BaseException:
            self._pushback(b"".join(chunks))
            raise
        return b"".join(chunks)

    # -- writing ------------------------------------------------------

    async def write(self, b: Any) -> int:
        """Buffer ``b``, writing through when the buffer is full.

        Returns ``len(b)``: a buffered write is always complete.

        If cancelled: a write that fits in the buffer was not taken at all.
        A larger one was taken, and whatever the kernel had not yet accepted
        stays buffered for the next flush.
        """
        self.raw._check_writable()
        if isinstance(b, str):
            raise TypeError("a bytes-like object is required, not 'str'")
        view = memoryview(b)
        n = view.nbytes
        if not n:
            return 0
        await self._reserve(n)
        self._append(view if view.format == "B" and view.ndim == 1 else view.cast("B"))
        if self._writes_through(n):
            await self.flush()
        return n

    async def _reserve(self, n: int) -> None:
        """Get ready to take ``n`` more bytes. Nothing has been taken, and
        nothing has changed that the caller could see, if this is cancelled."""
        if self._rend != self._rpos:
            self._rewind()
        if self._wbuf and len(self._wbuf) + n > self._size:
            await self.flush()
            if cancel_pending():
                # The flush finished after asyncio had cancelled us, and the
                # cancellation was put off to our next await. Take it here,
                # before anything is taken: had the caller's task ended
                # first, it would be reported cancelled.
                await asyncio.sleep(0)

    def _append(self, data: Any) -> None:
        self._wbuf += data

    def _writes_through(self, n: int) -> bool:
        """Whether a write of ``n`` bytes goes straight to the file rather
        than waiting in the buffer: one too big for the buffer does, and
        (since Python 3.13) so does one exactly as big."""
        return n > self._size or (n == self._size and _WRITE_THROUGH_WHEN_EQUAL)

    async def flush(self) -> None:
        raw = self.raw
        if raw._fd < 0:
            raise _closed()
        buf = self._wbuf
        if not buf:
            return
        size = len(buf)
        written = 0

        def landed(n: int) -> None:
            nonlocal written
            written += n

        view = memoryview(buf)
        try:
            while written < size:
                n = await raw._write(view[written:] if written else view, landed)
                if not n:
                    raise OSError(errno.EIO, "write returned zero bytes")
                written += n
        finally:
            # Replace rather than trim: on the way out of a failed write,
            # a traceback can still be holding views of the old buffer.
            self._wbuf = buf[written:] if written < size else bytearray()

    def flush_now(self) -> None:
        """Write out the buffer synchronously. For finalizers only."""
        buf, self._wbuf = self._wbuf, bytearray()
        fd = self.raw._fd
        while buf and fd >= 0:
            del buf[: os.write(fd, buf)]

    async def truncate(self, pos: int | None = None) -> int:
        self.raw._check_writable()
        await self.flush()
        self._rewind()
        return await self.raw.truncate(pos)

    async def fsync(self, datasync: bool = False) -> None:
        await self.flush()
        await self.raw.fsync(datasync)

    # -- position -----------------------------------------------------

    def _tell(self) -> int:
        return self.raw._tell() - (self._rend - self._rpos) + len(self._wbuf)

    async def tell(self) -> int:
        return self._tell()

    async def seek(self, pos: int, whence: int = SEEK_SET) -> int:
        if self._wbuf:
            await self.flush()
        if whence == SEEK_CUR:
            pos -= self._rend - self._rpos
        return self._seek_now(pos, whence)

    def _seek_now(self, pos: int, whence: int = SEEK_SET) -> int:
        """Move, with nothing waiting to be written."""
        new = self.raw._seek(pos, whence)
        self._rpos = self._rend = 0
        return new

    # -- closing ------------------------------------------------------

    async def close(self) -> None:
        """Flush and close.

        What if the flush is cancelled depends on what it could be waiting
        for. Writing to a regular file takes bounded time, so there the
        flush is shielded: closing a file never throws away what was
        written to it. A pipe or a terminal can refuse data indefinitely;
        there cancellation closes at once and the buffered data is dropped.
        """
        raw = self.raw
        if raw._fd < 0:
            return
        try:
            if self._wbuf:
                with CancelScope(shield=raw._regular):
                    await self.flush()
        finally:
            await raw.close()


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------


def _pack_cookie(
    position: int, dec_flags: int = 0, bytes_to_feed: int = 0,
    chars_to_skip: int = 0, need_eof: bool = False,
) -> int:  # fmt: skip
    # The layout of CPython's C TextIOWrapper (a 64-bit position, then three
    # 32-bit fields and a flag), so that cookies are interchangeable with
    # those of the built-in file objects. (The pure-Python _pyio differs.)
    return (
        position
        | (dec_flags << 64)
        | (bytes_to_feed << 96)
        | (chars_to_skip << 128)
        | (bool(need_eof) << 160)
    )


def _unpack_cookie(cookie: int) -> tuple[int, int, int, int, bool]:
    rest, position = divmod(cookie, 1 << 64)
    rest, dec_flags = divmod(rest, 1 << 32)
    rest, bytes_to_feed = divmod(rest, 1 << 32)
    need_eof, chars_to_skip = divmod(rest, 1 << 32)
    return position, dec_flags, bytes_to_feed, chars_to_skip, bool(need_eof)


def resolve_text_params(encoding: str | None, errors: str | None) -> tuple[str, str]:
    """Apply the interpreter's own defaults and validation for text mode."""
    probe = io.TextIOWrapper(io.BytesIO(), encoding=encoding, errors=errors)
    try:
        return probe.encoding, probe.errors or "strict"
    finally:
        probe.detach()


class Text:
    """Decoding, encoding and newline translation over a :class:`Buffered`.

    The decoded text not yet handed out is ``_decoded[_dpos:]``. Alongside it
    ``_snapshot = (decoder_flags, raw_bytes)`` records a decoder state and the
    exact bytes that, decoded from that state, produced ``_decoded``. That is
    what lets :meth:`tell` turn "so many characters into this chunk" back into
    a byte position, by the same replay CPython's ``TextIOWrapper`` uses.
    """

    _CHUNK = 8192

    def __init__(
        self,
        buffer: Buffered,
        encoding: str,
        errors: str,
        newline: str | None,
        line_buffering: bool = False,
        mode: str | None = None,
    ) -> None:
        if newline not in (None, "", "\n", "\r", "\r\n"):
            raise ValueError(f"illegal newline value: {newline!r}")
        self.buffer = buffer
        self.encoding = encoding
        self.errors = errors
        self.line_buffering = line_buffering
        self._mode = mode
        self._readuniversal = not newline
        self._readtranslate = newline is None
        self._readnl = newline
        self._writetranslate = newline != ""
        self._writenl = newline or os.linesep
        self._decoder: Any = None
        self._encoder: Any = None
        self._decoded = ""
        self._dpos = 0
        self._snapshot: tuple[int, bytes] | None = None
        self._seekable = self._telling = buffer.seekable()
        self._b2cratio = 0.0
        # A decoder exists exactly when the file is readable and an encoder
        # exactly when it is writable, as in the C TextIOWrapper. (Whether
        # one exists is visible: it decides what state seek() restores.)
        if buffer.readable():
            decoder: Any = codecs.getincrementaldecoder(encoding)(errors)
            if self._readuniversal:
                decoder = io.IncrementalNewlineDecoder(decoder, self._readtranslate)
            self._decoder = decoder
        if buffer.writable():
            self._encoder = codecs.getincrementalencoder(encoding)(errors)
            # Appending to a non-empty file must not write a second BOM.
            if self._seekable and buffer._tell() != 0:
                self._encoder.setstate(0)

    # -- introspection ------------------------------------------------

    @property
    def name(self) -> Any:
        return self.buffer.name

    @property
    def mode(self) -> str:
        return self._mode if self._mode is not None else self.buffer.mode

    @property
    def closed(self) -> bool:
        return self.buffer.closed

    @property
    def newlines(self) -> Any:
        # Only the universal-newlines decoder keeps track.
        return getattr(self._decoder, "newlines", None)

    def fileno(self) -> int:
        return self.buffer.fileno()

    def isatty(self) -> bool:
        return self.buffer.isatty()

    def readable(self) -> bool:
        return self.buffer.readable()

    def writable(self) -> bool:
        return self.buffer.writable()

    def seekable(self) -> bool:
        self.buffer.fileno()
        return self._seekable

    # -- codec plumbing -----------------------------------------------

    def _forget_decoded(self) -> None:
        self._decoded = ""
        self._dpos = 0
        self._snapshot = None

    def _take_decoded(self, n: int = -1) -> str:
        """Hand out up to ``n`` (or all) of the decoded characters not yet
        handed out."""
        pos = self._dpos
        text = self._decoded[pos:] if n < 0 else self._decoded[pos : pos + n]
        self._dpos = pos + len(text)
        return text

    def _rewind_decoded(self, n: int) -> None:
        """Take back the last ``n`` characters handed out, which must have
        come from the current chunk."""
        assert n <= self._dpos
        self._dpos -= n

    async def _read_chunk(self, size_hint: int, consumed: list[bytes]) -> bool:
        """Read and decode one more chunk, replacing ``_decoded``: whatever of
        it was not handed out must have been taken by the caller (with
        :meth:`_take_decoded`) first.

        CANCEL: the raw bytes are also added to ``consumed``, for :meth:`_undo`.

        Returns False once the file is exhausted and nothing more came out.
        """
        decoder = self._decoder
        if self._telling:
            # The decoder may hold undecoded bytes; a clean restart point lies
            # that many bytes back, with the decoder in state (b"", flags).
            pending, flags = decoder.getstate()
        chunk = await self.buffer.read1(max(self._CHUNK, size_hint))
        consumed.append(chunk)  # CANCEL: so that _undo can give them back
        eof = not chunk
        decoded = decoder.decode(chunk, eof)
        self._decoded = decoded
        self._dpos = 0
        self._b2cratio = len(chunk) / len(decoded) if decoded else 0.0
        if self._telling:
            self._snapshot = (flags, pending + chunk)
        # Reaching EOF can itself produce text (a held-back "\r", or the
        # decoder's verdict on a truncated sequence). That is not EOF yet.
        return not eof or bool(decoded)

    # -- reading ------------------------------------------------------
    #
    # read(n) and readline() are CPython's: the text gathered so far is kept
    # in a local, and each chunk read replaces the decoder's output and the
    # tell() snapshot outright, so that neither ever holds more than one
    # chunk. What CPython does not have to deal with is a call abandoned
    # half way with that local in hand. Here the call is undone instead: the
    # decoder and what it had decoded are put back as they were, and the
    # bytes read meanwhile go back into the buffer, to be read again.
    #
    # Everything that exists only for that is marked CANCEL. Take those
    # parts out and what is left is CPython's algorithm.

    # CANCEL: the two methods below.

    def _undo_point(self, dpos: int) -> tuple[Any, ...]:
        """The state to go back to: as it is now, but with ``dpos`` where
        the call found it, before taking what was already decoded."""
        return (
            self._decoded, dpos, self._snapshot, self._b2cratio, self._decoder.getstate()
        )  # fmt: skip

    def _undo(self, point: tuple[Any, ...] | None, consumed: list[bytes]) -> None:
        if point is None:  # nothing read yet: nothing to undo
            return
        self._decoded, self._dpos, self._snapshot, self._b2cratio, state = point
        self._decoder.setstate(state)
        self.buffer._pushback(b"".join(consumed))

    def _check_readable(self) -> Any:
        if not self.buffer.readable():  # raises if closed
            raise io.UnsupportedOperation("not readable")
        return self._decoder

    async def read(self, size: int | None = -1) -> str:
        decoder = self._check_readable()
        if size is None or size < 0:
            data = await self.buffer.read()
            result = self._take_decoded() + decoder.decode(data, True)
            self._forget_decoded()
            return result
        dpos = self._dpos  # CANCEL
        result = self._take_decoded(size)
        if len(result) == size:
            return result
        point = self._undo_point(dpos)  # CANCEL
        consumed: list[bytes] = []  # CANCEL
        parts = [result]
        missing = size - len(result)
        try:  # CANCEL {
            # Characters wanted, scaled to bytes by the ratio seen so far.
            while missing and await self._read_chunk(
                int(max(self._b2cratio, 1.0) * missing), consumed
            ):
                parts.append(part := self._take_decoded(missing))
                missing -= len(part)
        except BaseException as exc:
            if not isinstance(exc, Exception):  # cancelled, or interrupted
                self._undo(point, consumed)
            raise  # CANCEL }
        return "".join(parts)

    def _find_line_end(self, text: str, start: int, scan: int) -> tuple[int, int]:
        """Look for a line ending in ``text`` at or after ``scan``.

        Returns ``(end, scan)``: ``end`` is the index just past the ending, or
        -1 if there is none yet, in which case ``scan`` says where to resume.
        """
        if self._readtranslate:
            i = text.find("\n", scan)
            return (i + 1, 0) if i >= 0 else (-1, len(text))
        if self._readuniversal:
            # The newline decoder never ends a chunk on a bare "\r" unless at
            # EOF, so a "\r\n" pair is never split across two looks.
            nl = text.find("\n", scan)
            cr = text.find("\r", scan)
            if cr == -1:
                return (nl + 1, 0) if nl >= 0 else (-1, len(text))
            if nl == -1 or cr < nl - 1:
                return cr + 1, 0
            if nl < cr:
                return nl + 1, 0
            return cr + 2, 0  # "\r\n"
        sep = self._readnl
        assert sep
        i = text.find(sep, scan)
        if i >= 0:
            return i + len(sep), 0
        # The separator may straddle the end of what we have.
        return -1, max(start, len(text) - len(sep) + 1)

    async def readline(self, size: int | None = -1) -> str:
        self._check_readable()
        limit = -1 if size is None else size
        dpos = self._dpos  # CANCEL
        point = None  # CANCEL: made when there is first something to undo
        consumed: list[bytes] = []  # CANCEL
        line = self._take_decoded()
        scan = 0
        grow = self._CHUNK
        # Like the C implementation, look at one chunk even for readline(0)
        # on a fresh file; tell() can see the difference.
        need_more = not line
        hit_eof = False
        try:  # CANCEL {
            while True:
                if need_more:
                    if point is None:  # CANCEL
                        point = self._undo_point(dpos)  # CANCEL
                    more = await self._read_chunk(grow, consumed)
                    if not more:
                        end = len(line)
                        hit_eof = True
                        break
                    if line:
                        # A long line: ask for geometrically more, so that
                        # total work stays linear in the length of the line.
                        grow *= 2
                    line += self._take_decoded()
                end, scan = self._find_line_end(line, 0, scan)
                if end >= 0:
                    break
                if 0 <= limit <= len(line):
                    end = limit
                    break
                need_more = True
        except BaseException as exc:
            if not isinstance(exc, Exception):  # cancelled, or interrupted
                self._undo(point, consumed)
            raise  # CANCEL }
        if 0 <= limit < end:
            end = limit
        if hit_eof:
            self._forget_decoded()
        else:
            # Give back what follows the line. (The line did not end, nor
            # reach the limit, before the last chunk; so all of that is
            # from the last chunk.)
            self._rewind_decoded(len(line) - end)
        return line[:end]

    # -- writing ------------------------------------------------------

    async def write(self, s: str) -> int:
        if not isinstance(s, str):
            raise TypeError(f"can't write {s.__class__.__name__} to text stream")
        buffer = self.buffer
        if not buffer.writable():
            raise io.UnsupportedOperation("not writable")
        length = len(s)
        has_lf = (self._writetranslate or self.line_buffering) and "\n" in s
        if has_lf and self._writetranslate and self._writenl != "\n":
            s = s.replace("\n", self._writenl)
        encoder = self._encoder
        # Encoding moves the encoder on (a BOM is now behind it, or it is in
        # a different shift state), which must be undone if the bytes turn
        # out not to be taken.
        before = encoder.getstate()
        data = encoder.encode(s)
        try:
            await buffer._reserve(len(data))
        except BaseException:
            encoder.setstate(before)
            raise
        buffer._append(data)
        # Writing invalidates read-ahead. (Like the standard library, this
        # does not rewind to where the reader logically was; seek first.)
        if self._snapshot is not None:
            self._forget_decoded()
        if self._decoder:
            self._decoder.reset()
        if buffer._writes_through(len(data)) or (self.line_buffering and (has_lf or "\r" in s)):
            await buffer.flush()
        return length

    async def flush(self) -> None:
        await self.buffer.flush()

    async def truncate(self, pos: int | None = None) -> int:
        # With no argument this cuts at the *buffer's* position, which after
        # a read is wherever read-ahead got to. That is what the built-in
        # text files do (unlike _pyio, which uses tell()); seek first.
        await self.flush()
        return await self.buffer.truncate(pos)

    async def fsync(self, datasync: bool = False) -> None:
        await self.buffer.fsync(datasync)

    # -- position -----------------------------------------------------

    async def tell(self) -> int:
        if not self.seekable():
            raise io.UnsupportedOperation("underlying stream is not seekable")
        await self.flush()
        position = self.buffer._tell()
        decoder = self._decoder
        if decoder is None or self._snapshot is None:
            return position

        flags, fed = self._snapshot
        position -= len(fed)  # where the snapshot's bytes begin
        skip = self._dpos  # characters consumed since then
        if not skip:
            return _pack_cookie(position, flags)

        # Find the byte offset within `fed` that corresponds to `skip`
        # characters. Decoders can buffer input and emit several characters
        # at once, so this has to be found by replaying, and the answer is a
        # restart point (a place where the decoder holds no buffered input)
        # plus a count of bytes to feed and characters to drop from there.
        saved = decoder.getstate()
        try:
            # Guess a byte offset from the bytes-per-character ratio seen so
            # far, then back off until it is a restart point short of `skip`.
            #
            # Strictly short. CPython also accepts a guess that lands exactly
            # on `skip`, but several restart points can share a character
            # count (before and after a "\r" that the newline decoder is
            # holding back, for one), so which cookie comes out then depends
            # on the guess. Stopping short and walking forward always yields
            # the earliest, which is a plain byte offset whenever the
            # position has one.
            offset = min(int(self._b2cratio * skip), len(fed))
            step = 1
            while offset > 0:
                decoder.setstate((b"", flags))
                n = len(decoder.decode(fed[:offset]))
                if n < skip:
                    held, held_flags = decoder.getstate()
                    if not held:
                        flags = held_flags
                        skip -= n
                        break
                    offset -= len(held)
                    step = 1
                else:
                    offset -= step
                    step *= 2
            else:
                offset = 0
                decoder.setstate((b"", flags))

            start, start_flags = position + offset, flags

            # Walk forward a byte at a time, moving the restart point up
            # whenever the decoder comes clean, until `skip` characters have
            # been produced.
            feed = produced = 0
            need_eof = False
            for i in range(offset, len(fed)):
                feed += 1
                produced += len(decoder.decode(fed[i : i + 1]))
                held, held_flags = decoder.getstate()
                if not held and produced <= skip:
                    start += feed
                    skip -= produced
                    start_flags, feed, produced = held_flags, 0, 0
                if produced >= skip:
                    break
            else:
                produced += len(decoder.decode(b"", True))
                need_eof = True
                if produced < skip:
                    raise OSError("can't reconstruct logical file position")
            return _pack_cookie(start, start_flags, feed, skip, need_eof)
        finally:
            decoder.setstate(saved)

    def _reset_encoder(self, at_start: bool) -> None:
        encoder = self._encoder
        if encoder is not None:
            if at_start:
                encoder.reset()
            else:
                encoder.setstate(0)  # no BOM in the middle of a file

    async def seek(self, cookie: int, whence: int = SEEK_SET) -> int:
        if not self.seekable():
            raise io.UnsupportedOperation("underlying stream is not seekable")
        if whence == SEEK_CUR:
            if cookie != 0:
                raise io.UnsupportedOperation("can't do nonzero cur-relative seeks")
            whence = SEEK_SET
            cookie = await self.tell()
        elif whence == SEEK_END:
            if cookie != 0:
                raise io.UnsupportedOperation("can't do nonzero end-relative seeks")
            await self.flush()
            position = await self.buffer.seek(0, SEEK_END)
            self._forget_decoded()
            if self._decoder:
                self._decoder.reset()
            self._reset_encoder(position == 0)
            return position
        if whence != SEEK_SET:
            raise ValueError(f"unsupported whence ({whence!r})")
        if cookie < 0:
            raise ValueError(f"negative seek position {cookie!r}")
        await self.flush()

        start, flags, feed, skip, need_eof = _unpack_cookie(cookie)
        buffer = self.buffer
        before = buffer._tell()
        await buffer.seek(start)
        chunk = b""
        if skip:
            # The target lies inside a run of bytes that only decodes as a
            # whole; fetch the run. If that is interrupted, go back, so that
            # a cancelled seek is one that did not happen.
            try:
                chunk = await buffer.read(feed)
            except BaseException:
                buffer._seek_now(before)
                raise
        self._restore_decoder(cookie, flags, skip)
        if skip:
            self._restore_chunk(flags, skip, need_eof, chunk)
        self._reset_encoder(cookie == 0)
        return cookie

    def _restore_decoder(self, cookie: int, flags: int, skip: int) -> None:
        """First half of seeking to a cookie: the buffer is at its restart
        point; put the decoder in the state it had there."""
        self._forget_decoded()
        decoder = self._decoder
        if decoder is not None:
            if cookie == 0:
                # Not setstate((b"", 0)): for some codecs the initial state
                # is something else (UTF-16 before it has seen a BOM, say).
                decoder.reset()
            else:
                decoder.setstate((b"", flags))
                self._snapshot = (flags, b"")

    def _restore_chunk(self, flags: int, skip: int, need_eof: bool, chunk: bytes) -> None:
        """Second half: re-decode the bytes between the restart point and
        the target, and drop the characters that precede the target."""
        # (In this order, so that a stale cookie, one from before the file
        # was rewritten, fails the same way it does for the built-in files.)
        self._snapshot = (flags, chunk)
        self._decoded = self._decoder.decode(chunk, need_eof)
        if len(self._decoded) < skip:
            raise OSError("can't restore logical file position")
        self._dpos = skip

    # -- closing ------------------------------------------------------

    async def close(self) -> None:
        await self.buffer.close()
