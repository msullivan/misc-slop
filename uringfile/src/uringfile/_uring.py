"""Minimal io_uring bindings in pure Python.

The three io_uring syscalls are made through :mod:`ctypes`; the rings shared
with the kernel are mapped with :mod:`mmap` and read and written with
:mod:`struct`. Nothing here knows about event loops: :class:`Ring` is a
synchronous object that queues submissions and hands back completions.

Only the single-threaded, non-SQPOLL mode is supported, which keeps the
shared-memory protocol simple:

* The kernel only looks at the submission queue from inside
  ``io_uring_enter``, which we call on the same thread that filled it in, so
  the SQ side needs no ordering guarantees at all.
* The completion queue is written by the kernel from other CPUs. See the
  note in :meth:`Ring.drain` for what we rely on there.
"""

from __future__ import annotations

import ctypes
import errno
import mmap
import os
import struct
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from _typeshed import ReadableBuffer

__all__ = ["Ring", "readable_address", "stat_cached", "writable_address"]

# Syscall numbers. io_uring arrived after the kernel unified new syscall
# numbers across architectures, so these hold everywhere except alpha.
_NR_SETUP = 425
_NR_ENTER = 426
_NR_REGISTER = 427

# Opcodes (enum io_uring_op).
OP_NOP = 0
OP_FSYNC = 3
OP_POLL_ADD = 6
OP_ASYNC_CANCEL = 14
OP_OPENAT = 18
OP_CLOSE = 19
OP_READ = 22
OP_WRITE = 23
OP_FTRUNCATE = 55  # Linux 6.9

#: SQE flag: skip the inline non-blocking attempt, go straight to a worker.
SQE_ASYNC = 1 << 4

SETUP_CQSIZE = 1 << 3
SETUP_COOP_TASKRUN = 1 << 8  # Linux 5.19

FEAT_SINGLE_MMAP = 1 << 0
FEAT_NODROP = 1 << 1
FEAT_RW_CUR_POS = 1 << 3

ENTER_GETEVENTS = 1 << 0
SQ_CQ_OVERFLOW = 1 << 1

REGISTER_EVENTFD = 4
REGISTER_PROBE = 8
REGISTER_IOWQ_MAX_WORKERS = 19  # Linux 5.15
_OP_SUPPORTED = 1 << 0

FSYNC_DATASYNC = 1 << 0

_OFF_SQ_RING = 0
_OFF_CQ_RING = 0x8000000
_OFF_SQES = 0x10000000

#: ``off`` value meaning "use and advance the file position", like read(2).
CUR_POS = 0xFFFF_FFFF_FFFF_FFFF

_U32 = struct.Struct("=I")
# struct io_uring_params: 10 u32, then io_sqring_offsets and
# io_cqring_offsets, each 8 u32 followed by a u64.
_PARAMS = struct.Struct("=10I8IQ8IQ")
# struct io_uring_sqe: opcode, flags, ioprio, fd, off, addr, len, op_flags,
# user_data, buf_index, personality, file_index, addr3, pad.
_SQE = struct.Struct("=BBHiQQIIQHHiQQ")
# struct io_uring_cqe: user_data, res, flags.
_CQE = struct.Struct("=QiI")
assert _PARAMS.size == 120 and _SQE.size == 64 and _CQE.size == 16

_libc = ctypes.CDLL(None, use_errno=True)


def _syscall(*argtypes: Any) -> Any:
    """A binding of libc's variadic syscall() with one fixed signature.

    Declaring the argument types lets ctypes convert plain ints itself,
    which is cheaper than wrapping each one on every call.
    """
    proto = ctypes.CFUNCTYPE(ctypes.c_long, ctypes.c_long, *argtypes, use_errno=True)
    return proto(("syscall", _libc))


_c_uint, _c_void_p = ctypes.c_uint, ctypes.c_void_p
# int io_uring_setup(u32 entries, struct io_uring_params *p)
_setup = _syscall(_c_uint, _c_void_p)
# int io_uring_enter(unsigned fd, unsigned to_submit, unsigned min_complete,
#                    unsigned flags, sigset_t *sig, size_t sigsz)
_enter = _syscall(_c_uint, _c_uint, _c_uint, _c_uint, _c_void_p, ctypes.c_size_t)
# int io_uring_register(unsigned fd, unsigned opcode, void *arg, unsigned nr_args)
_register = _syscall(_c_uint, _c_uint, _c_void_p, _c_uint)


def _check(ret: int) -> int:
    if ret < 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))
    return ret


_AT_EMPTY_PATH = 0x1000
_AT_STATX_DONT_SYNC = 0x4000
_STATX_BASIC_STATS = 0x7FF
_statx: Any
try:
    # int statx(int dirfd, const char *path, int flags, unsigned mask, struct statx *buf)
    _statx = ctypes.CFUNCTYPE(
        ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int, _c_uint, _c_void_p,
        use_errno=True,
    )(("statx", _libc))  # fmt: skip
except AttributeError:  # a C library older than the system call
    _statx = None


def stat_cached(fd: int) -> tuple[int, int, int]:
    """Return ``(st_mode, st_size, st_blksize)`` of an open file, without I/O.

    This is a plain system call, not a ring operation, and that is safe
    because of the flag it passes: ``AT_STATX_DONT_SYNC`` tells the kernel
    to answer from what it has in memory even on a network filesystem,
    where an ordinary fstat() may go to the server. What comes back can
    therefore be slightly stale, which is fine for what it is used for:
    the file type, and sizes that only serve as hints.

    (The ring's own statx is no alternative for the common case: the kernel
    always runs it on a worker thread, and that hand-off costs several times
    what opening and reading a small cached file does.)
    """
    if _statx is None:
        st = os.fstat(fd)
        return st.st_mode, st.st_size, st.st_blksize
    buf = ctypes.create_string_buffer(256)
    flags = _AT_EMPTY_PATH | _AT_STATX_DONT_SYNC
    if _statx(fd, b"", flags, _STATX_BASIC_STATS, ctypes.addressof(buf)) < 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))
    # struct statx: stx_blksize at 4, stx_mode at 28, stx_size at 40.
    blksize = struct.unpack_from("=I", buf, 4)[0]
    mode = struct.unpack_from("=H", buf, 28)[0]
    size = struct.unpack_from("=Q", buf, 40)[0]
    return mode, size, blksize


def _map(fd: int, length: int, offset: int) -> mmap.mmap:
    kwargs: dict[str, Any] = {}
    if sys.version_info >= (3, 13):
        kwargs["trackfd"] = False  # don't keep a dup of the ring fd around
    return mmap.mmap(
        fd,
        length,
        flags=mmap.MAP_SHARED | mmap.MAP_POPULATE,
        prot=mmap.PROT_READ | mmap.PROT_WRITE,
        offset=offset,
        **kwargs,
    )


def writable_address(buf: memoryview) -> tuple[int, object]:
    """Return ``(address, keepalive)`` for a writable contiguous buffer.

    The keepalive holds a buffer export, so the exporter (a ``bytearray``,
    say) cannot be resized or freed while the kernel may still write to it.
    """
    arr = (ctypes.c_char * len(buf)).from_buffer(buf)
    return ctypes.addressof(arr), arr


def readable_address(data: ReadableBuffer) -> tuple[int, int, object]:
    """Return ``(address, length, keepalive)`` for any bytes-like object."""
    if not isinstance(data, bytes):
        view = memoryview(data)
        if not view.readonly and view.c_contiguous:
            view = view.cast("B")
            if not len(view):
                return 0, 0, None
            addr, keep = writable_address(view)
            return addr, len(view), keep
        # ctypes can't take the address of a read-only export; copy.
        data = bytes(view)
    ptr = ctypes.c_char_p(data)  # points into the bytes object, no copy
    return ctypes.cast(ptr, ctypes.c_void_p).value or 0, len(data), (ptr, data)


class Ring:
    """One io_uring instance."""

    def __init__(self, entries: int = 256) -> None:
        self.fd = -1
        self._maps: list[mmap.mmap] = []
        params = ctypes.create_string_buffer(_PARAMS.size)
        # COOP_TASKRUN: don't interrupt this thread to run completion work;
        # it goes into the kernel often enough on its own.
        for flags in (SETUP_COOP_TASKRUN, 0):
            _PARAMS.pack_into(params, 0, 0, 0, flags, *([0] * 25))
            fd = _setup(_NR_SETUP, entries, ctypes.addressof(params))
            if fd >= 0:
                break
            err = ctypes.get_errno()
            if err != errno.EINVAL or not flags:
                raise OSError(err, f"io_uring_setup: {os.strerror(err)}")
        self.fd = fd
        try:
            p = _PARAMS.unpack_from(params)
            self.sq_entries, self.cq_entries, self.flags = p[0], p[1], p[2]
            self.features = p[5]
            sq_off, cq_off = p[10:19], p[19:28]
            (
                self._sq_head_off,
                self._sq_tail_off,
                sq_mask_off,
                _,
                self._sq_flags_off,
                _,
                sq_array_off,
                _,
                _,
            ) = sq_off
            (
                self._cq_head_off,
                self._cq_tail_off,
                cq_mask_off,
                _,
                self._cq_overflow_off,
                self._cqes_off,
                _,
                _,
                _,
            ) = cq_off

            sq_len = sq_array_off + self.sq_entries * _U32.size
            cq_len = self._cqes_off + self.cq_entries * _CQE.size
            if self.features & FEAT_SINGLE_MMAP:
                self._sq = self._cq = self._map(max(sq_len, cq_len), _OFF_SQ_RING)
            else:
                self._sq = self._map(sq_len, _OFF_SQ_RING)
                self._cq = self._map(cq_len, _OFF_CQ_RING)
            self._sqes = self._map(self.sq_entries * _SQE.size, _OFF_SQES)

            self._sq_mask = _U32.unpack_from(self._sq, sq_mask_off)[0]
            self._cq_mask = _U32.unpack_from(self._cq, cq_mask_off)[0]
            # The SQ is an array of indices into the SQE array. We never
            # reorder, so make it the identity once and forget about it.
            for i in range(self.sq_entries):
                _U32.pack_into(self._sq, sq_array_off + i * _U32.size, i)
            self._sq_tail = _U32.unpack_from(self._sq, self._sq_tail_off)[0]
            self._cq_head = _U32.unpack_from(self._cq, self._cq_head_off)[0]
        except BaseException:
            self.close()
            raise

    # -- submission ---------------------------------------------------

    @property
    def pending(self) -> int:
        """SQEs written but not (yet) taken by the kernel.

        Computed from the kernel's own SQ head rather than counted, so that
        it stays true even if an exception (a signal handler's, say) cuts
        :meth:`submit` short just after the system call returned.
        """
        head = _U32.unpack_from(self._sq, self._sq_head_off)[0]
        return (self._sq_tail - head) & 0xFFFFFFFF

    @property
    def tail(self) -> int:
        """Advances by one for every :meth:`push`."""
        return self._sq_tail

    def push(
        self,
        opcode: int,
        fd: int,
        off: int,
        addr: int,
        length: int,
        op_flags: int,
        user_data: int,
        sqe_flags: int = 0,
    ) -> None:
        """Write one SQE. It reaches the kernel on the next :meth:`submit`."""
        if self.pending >= self.sq_entries:
            raise BufferError("submission queue is full")
        index = self._sq_tail & self._sq_mask
        _SQE.pack_into(
            self._sqes, index * _SQE.size,
            opcode, sqe_flags, 0, fd, off, addr, length, op_flags, user_data, 0, 0, 0, 0, 0,
        )  # fmt: skip
        self._sq_tail = (self._sq_tail + 1) & 0xFFFFFFFF

    def unpush(self) -> None:
        """Take back the most recent :meth:`push` if the kernel has not got it."""
        if self.pending:
            self._sq_tail = (self._sq_tail - 1) & 0xFFFFFFFF
            _U32.pack_into(self._sq, self._sq_tail_off, self._sq_tail)

    def submit(self) -> int:
        """Hand pending SQEs to the kernel; return how many it took.

        This does not wait for anything. Operations that can finish without
        blocking do finish inside this call and are visible to the next
        :meth:`reap`.
        """
        _U32.pack_into(self._sq, self._sq_tail_off, self._sq_tail)
        n = _enter(_NR_ENTER, self.fd, self.pending, 0, 0, None, 0)
        if n < 0:
            _check(n)
        return n

    # -- completion ---------------------------------------------------

    def drain(self, handle: Callable[[int, int], object]) -> None:
        """Call ``handle(user_data, res)`` for every ready completion.

        Each completion is released to the kernel only after its handler has
        returned. If something interrupts this half way, the completion being
        handled is simply seen again next time, so handlers must not mind
        being called twice for the same one.
        """
        cq = self._cq
        head = self._cq_head
        while True:
            # The kernel writes a CQE and then publishes it by storing the
            # new tail with release semantics; a correct consumer loads the
            # tail with acquire semantics before reading the entry. Pure
            # Python has no acquire load. On x86 (TSO) a plain load is one.
            # On weakly ordered CPUs this is not justified by the
            # architecture, only by the fact that the two loads below are
            # separated by thousands of interpreter instructions, far more
            # than any core can hold in flight to reorder them.
            tail = _U32.unpack_from(cq, self._cq_tail_off)[0]
            if head == tail:
                break
            while head != tail:
                user_data, res, _flags = _CQE.unpack_from(
                    cq, self._cqes_off + (head & self._cq_mask) * _CQE.size
                )
                handle(user_data, res)
                head = (head + 1) & 0xFFFFFFFF
                self._cq_head = head
                # The kernel reads the head only to see how much room is
                # left; a stale value just makes it more conservative.
                _U32.pack_into(cq, self._cq_head_off, head)

    def reap(self) -> list[tuple[int, int]]:
        """Return and consume all ready completions as ``(user_data, res)``."""
        out: list[tuple[int, int]] = []
        self.drain(lambda user_data, res: out.append((user_data, res)))
        return out

    @property
    def overflowed(self) -> bool:
        """True if completions are parked in the kernel for lack of CQ space."""
        return bool(_U32.unpack_from(self._sq, self._sq_flags_off)[0] & SQ_CQ_OVERFLOW)

    def flush_overflow(self) -> None:
        """Ask the kernel to move parked completions into the (emptied) CQ."""
        _check(_enter(_NR_ENTER, self.fd, 0, 0, ENTER_GETEVENTS, None, 0))

    # -- registration -------------------------------------------------

    def register_eventfd(self, efd: int) -> None:
        """Have the kernel signal ``efd`` whenever it posts a completion."""
        arg = ctypes.c_int(efd)
        _check(_register(_NR_REGISTER, self.fd, REGISTER_EVENTFD, ctypes.addressof(arg), 1))

    def set_max_workers(self, bounded: int, unbounded: int = 0) -> tuple[int, int]:
        """Limit the kernel worker threads that run operations which block.

        The pool belongs to the calling thread, not to the ring: every ring
        the thread creates shares it. Zero leaves a limit as it is. Returns
        the previous ``(bounded, unbounded)`` limits.
        """
        arg = (ctypes.c_uint * 2)(bounded, unbounded)
        _check(
            _register(_NR_REGISTER, self.fd, REGISTER_IOWQ_MAX_WORKERS, ctypes.addressof(arg), 2)
        )
        return arg[0], arg[1]

    def probe(self) -> frozenset[int]:
        """Return the set of opcodes this kernel supports."""
        nops = 256
        buf = ctypes.create_string_buffer(16 + 8 * nops)
        _check(_register(_NR_REGISTER, self.fd, REGISTER_PROBE, ctypes.addressof(buf), nops))
        _last_op, ops_len = struct.unpack_from("=BB", buf, 0)
        supported = set()
        for i in range(ops_len):
            op, _, flags = struct.unpack_from("=BBH", buf, 16 + 8 * i)
            if flags & _OP_SUPPORTED:
                supported.add(op)
        return frozenset(supported)

    # -- teardown -----------------------------------------------------

    @property
    def closed(self) -> bool:
        return self.fd < 0

    def _map(self, length: int, offset: int) -> mmap.mmap:
        m = _map(self.fd, length, offset)
        self._maps.append(m)
        return m

    def close(self) -> None:
        # The maps stay around, closed: anything that still tries to use the
        # ring gets a ValueError from them rather than touching freed memory.
        for m in self._maps:
            m.close()
        fd, self.fd = self.fd, -1
        if fd >= 0:
            os.close(fd)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
