"""Bridge between an io_uring and the running event loop.

Each event loop gets one :class:`Driver`, created on first use: a ring plus
an eventfd that the kernel signals whenever it posts a completion. A task
that has to wait for its completion sleeps until the eventfd is signalled,
and that sleep is the only point of contact with the event loop.

There is no background task (anyio has no portable way to spawn one outside
a task group). Instead, waiting tasks take turns: at most one of them, the
*driver*, sleeps on the eventfd and dispatches whatever completions arrive,
waking the tasks they belong to. The others just wait to be woken. When the
driver's own operation finishes, or it is cancelled, it nudges one of the
others to take over.

How the driver sleeps is the one thing that depends on the event loop. On
Trio it is :func:`anyio.wait_readable`. On asyncio that function adds and
removes a reader on every call, which costs two ``epoll_ctl`` system calls
and more than the rest of the wait put together, so there the eventfd gets
a reader once, for good, and the driver waits on a future that the reader
callback resolves.
"""

from __future__ import annotations

import asyncio
import ctypes
import errno
import os
import sys
import weakref
from collections.abc import Callable
from time import monotonic
from typing import TYPE_CHECKING

from anyio import CancelScope, Event, get_cancelled_exc_class, to_thread, wait_readable
from anyio.lowlevel import RunVar, cancel_shielded_checkpoint, checkpoint_if_cancelled

from . import _uring
from ._uring import CUR_POS, Ring, readable_address, writable_address

if TYPE_CHECKING:
    from _typeshed import ReadableBuffer

__all__ = ["Driver", "current_driver"]

_AT_FDCWD = -100
#: Largest length the kernel accepts for one read or write (MAX_RW_COUNT).
MAX_RW = 0x7FFF_F000
#: How many operations may be blocked in the kernel at once before further
#: ones that need a worker thread queue up behind them. Blocked means things
#: like a FIFO open waiting for its peer or a read from a stalled network
#: mount; ordinary disk I/O comes and goes. The kernel's own default is the
#: smaller of four per CPU and the queue depth of *the first ring the thread
#: ever made*, which is not a number anybody chose. This is anyio's default
#: limit on worker threads, which do the same job there.
MAX_WORKERS = 40
#: Longest a task making back-to-back calls that complete without blocking
#: can go without yielding to the event loop, in seconds.
YIELD_INTERVAL = 0.0005

_ECANCELED = -errno.ECANCELED
_EINTR = -errno.EINTR

# Buffers belonging to operations that were still in flight when their ring
# was torn down. The kernel may write to them for a moment longer, so they
# are deliberately never freed.
_graveyard: list[object] = []

_drivers: weakref.WeakSet[Driver] = weakref.WeakSet()


class _Op:
    __slots__ = ("__weakref__", "done", "event", "id", "keep", "res")

    def __init__(self, id: int, keep: object) -> None:
        self.id = id
        self.res = 0
        self.done = False
        self.keep = keep  # whatever must stay alive until the kernel is done
        self.event: Event | None = None  # set while parked behind a driver


class Driver:
    """A ring, its eventfd, and the bookkeeping to await completions."""

    def __init__(self, entries: int = 256) -> None:
        _protect_from_trio_ki()
        self._efd = -1
        self._ring = Ring(entries)
        try:
            self._efd = os.eventfd(0, os.EFD_NONBLOCK | os.EFD_CLOEXEC)
            self._ring.register_eventfd(self._efd)
            self.supported = self._ring.probe()
            try:
                self._ring.set_max_workers(MAX_WORKERS)
            except OSError:
                pass  # kernels before 5.15: live with the default
        except BaseException:
            self.close()
            raise
        self._inflight: dict[int, _Op] = {}
        self._seq = 0
        self._driving = False
        self._parked: dict[_Op, None] = {}  # insertion-ordered set
        # asyncio only: the loop that has a reader on the eventfd, which
        # eventfd that is, and the future the driving task is asleep on.
        self._watcher: weakref.ref[asyncio.AbstractEventLoop] | None = None
        self._watched = -1
        self._waiter: asyncio.Future[None] | None = None
        # When a task of ours last came back from the event loop.
        self._yielded = 0.0
        _drivers.add(self)

    # -- lifecycle ----------------------------------------------------

    @property
    def closed(self) -> bool:
        return self._ring.closed

    def close(self) -> None:
        """Tear the ring down.

        Normally nothing is in flight when this happens: it runs when the
        event loop that owned the driver is garbage collected. If operations
        are still running, their waiters are released with ``ECANCELED``,
        and since the kernel may go on writing to their buffers for a moment
        after the ring is gone, those are leaked rather than freed.
        """
        inflight = getattr(self, "_inflight", {})
        ops = list(inflight.values())
        inflight.clear()
        for op in ops:
            if op.keep is not None:
                _graveyard.append(op.keep)
            op.res = _ECANCELED
            op.done = True
        self._ring.close()
        efd, self._efd = self._efd, -1
        if efd >= 0:
            if getattr(self, "_driving", False):
                # A task is asleep on it. Closing it now would leave that
                # task asleep for good; wake it and let it do the closing.
                os.eventfd_write(efd, 1)
            else:
                self._release(efd)
        for op in ops:
            if op.event is not None:
                try:
                    op.event.set()
                except Exception:
                    pass  # its event loop is gone as well

    def _release(self, efd: int) -> None:
        """Close the eventfd, taking it out of the event loop first."""
        watcher = getattr(self, "_watcher", None)
        if watcher is not None:
            self._watcher, self._watched = None, -1
            loop = watcher()
            # (A closed loop has dropped its readers already. One that keeps
            # a reader for a closed descriptor trips over it as soon as the
            # number is used again.)
            if loop is not None and not loop.is_closed():
                loop.remove_reader(efd)
        os.close(efd)

    def __del__(self) -> None:
        # Unreachable, so no task can be asleep on the eventfd any more.
        self._driving = False
        try:
            self.close()
        except Exception:
            pass

    # -- submission and completion ------------------------------------

    def _complete(self, user_data: int, res: int) -> None:
        op = self._inflight.get(user_data)
        if op is None:
            return  # the reply to one of our own cancel requests, or a repeat
        op.res = res
        op.done = True
        op.keep = None
        if op.event is not None:
            op.event.set()
        # Forgotten last: if we are interrupted before here, the ring shows
        # us this completion again and the steps above are simply redone.
        del self._inflight[user_data]

    def _dispatch(self) -> None:
        """Consume ready completions and wake whoever was waiting on them."""
        ring = self._ring
        while True:
            ring.drain(self._complete)
            # If the CQ filled up, the kernel parked further completions on
            # an internal list and did not signal the eventfd for them. Now
            # that there is room, pull them in.
            if not ring.overflowed:
                break
            ring.flush_overflow()

    def _submit(self) -> None:
        ring = self._ring
        retries = 0
        while ring.pending:
            try:
                if ring.submit():
                    continue
                error = OSError(errno.EIO, "io_uring_enter is not taking submissions")
            except InterruptedError:
                continue
            except OSError as exc:
                # EBUSY: completions are backed up; EAGAIN: out of request
                # memory. Either way, making room may help.
                if exc.errno not in (errno.EBUSY, errno.EAGAIN):
                    raise
                error = exc
            retries += 1
            if retries > 8:
                raise error
            ring.flush_overflow()
            self._dispatch()

    def _start(
        self, opcode: int, fd: int, off: int, addr: int, length: int, op_flags: int,
        keep: object, sqe_flags: int = 0,
    ) -> _Op:  # fmt: skip
        ring = self._ring
        if ring.closed:
            raise RuntimeError("this event loop's io_uring has been closed")
        self._seq = seq = self._seq + 1  # user_data 0 is reserved for cancels
        op = _Op(seq, keep)
        tail = ring.tail
        # Registered before the request exists, so that there is no moment
        # at which the kernel could know of it and we not hold its buffers.
        self._inflight[seq] = op
        try:
            ring.push(opcode, fd, off, addr, length, op_flags, seq, sqe_flags)
            self._submit()
        except BaseException:
            # Forget the operation only if the kernel provably never got it.
            # "An exception was raised" does not prove that: a signal
            # handler's exception can surface just as io_uring_enter returns,
            # after the kernel has taken the request.
            pushed = ring.tail != tail
            if pushed and ring.pending:
                ring.unpush()
                pushed = False
            if not pushed:
                self._inflight.pop(seq, None)
            raise
        # Anything that could finish without blocking already has.
        self._dispatch()
        return op

    def _cancel(self, op: _Op) -> None:
        ring = self._ring
        if ring.closed:
            return
        tail = ring.tail
        try:
            ring.push(_uring.OP_ASYNC_CANCEL, -1, 0, op.id, 0, 0, 0)
            self._submit()
        except Exception:
            # Best effort: the caller waits for the operation either way.
            if ring.tail != tail:
                ring.unpush()

    async def _wait(self, op: _Op) -> None:
        """Wait until ``op`` has completed, driving the ring if nobody else is."""
        efd = self._efd
        try:
            while not op.done:
                if self._driving:
                    op.event = Event()
                    self._parked[op] = None
                    try:
                        await op.event.wait()
                    finally:
                        del self._parked[op]
                        op.event = None
                else:
                    self._driving = True
                    try:
                        # Clear the eventfd first and look second, so that a
                        # completion landing in between leaves it readable.
                        try:
                            os.eventfd_read(efd)
                        except BlockingIOError:
                            pass
                        self._dispatch()
                        if not op.done:
                            await self._signalled(efd)
                    finally:
                        self._driving = False
                        if self._efd != efd:
                            self._release(efd)  # close() ran meanwhile; see there
        finally:
            # We are leaving. If we were the driver, or were the one woken to
            # become it, somebody else has to take over.
            if not self._driving:
                for other in self._parked:
                    other.event.set()  # type: ignore[union-attr]
                    break

    async def _signalled(self, efd: int) -> None:
        """Sleep until the kernel signals the eventfd."""
        if get_cancelled_exc_class() is not asyncio.CancelledError:
            await wait_readable(efd)
            return
        loop = asyncio.get_running_loop()
        if self._watcher is None or self._watcher() is not loop:
            # First wait in this loop. (A driver made by hand, rather than
            # by current_driver(), can see more than one loop in its life.)
            try:
                loop.add_reader(efd, self._on_signal)
            except NotImplementedError:  # not a loop that can watch descriptors
                await wait_readable(efd)
                return
            previous = self._watcher() if self._watcher is not None else None
            if previous is not None and not previous.is_closed():
                previous.remove_reader(efd)
            self._watcher, self._watched = weakref.ref(loop), efd
        self._waiter = waiter = loop.create_future()
        try:
            await waiter
        finally:
            self._waiter = None

    def _on_signal(self) -> None:
        # Called by the asyncio loop whenever the eventfd is readable, with
        # or without anybody waiting: it is the read here that keeps a
        # signalled eventfd from waking the loop over and over.
        efd = self._watched
        if efd < 0:
            return
        try:
            os.eventfd_read(efd)
        except BlockingIOError:
            # The driving task read it before the loop got round to calling
            # us, so it has seen everything there was. Waking it (it may be
            # waiting again by now) would be for nothing.
            return
        waiter = self._waiter
        if waiter is not None and not waiter.done():
            waiter.set_result(None)

    async def run(
        self,
        opcode: int,
        fd: int,
        off: int = 0,
        addr: int = 0,
        length: int = 0,
        op_flags: int = 0,
        keep: object = None,
        late: Callable[[int], object] | None = None,
        sqe_flags: int = 0,
    ) -> int:
        """Perform one operation and return its raw result (negative errno on error).

        Cancellation is passed on to the kernel, and this then waits for the
        kernel's verdict before re-raising, so that no operation is ever
        left running against a buffer the caller thinks it has back.
        If the operation finished anyway, ``late`` is called with its result
        first: the caller lost the race to cancel and gets one chance to
        account for what happened (keep the bytes that were read, close the
        descriptor that was opened) before the cancellation propagates.
        """
        await checkpoint_if_cancelled()
        cancelled = get_cancelled_exc_class()
        try:
            op = self._start(opcode, fd, off, addr, length, op_flags, keep, sqe_flags)
            try:
                if not op.done:
                    try:
                        await self._wait(op)
                    finally:
                        self._yielded = monotonic()
                elif monotonic() - self._yielded >= YIELD_INTERVAL:
                    # Finished without blocking. Cancellation was checked
                    # above; what is left of a checkpoint is giving other
                    # tasks a turn, and doing that on every call would
                    # double the cost of the ones the kernel can answer on
                    # the spot. So yield only if it has been a while.
                    try:
                        await cancel_shielded_checkpoint()
                    finally:
                        self._yielded = monotonic()
            except cancelled:
                if not op.done:
                    self._cancel(op)
                    # Now wait for the kernel's verdict, however long that
                    # takes. An anyio shield holds off anyio's cancellation
                    # but not asyncio's own (Task.cancel, asyncio.timeout),
                    # so further ones can arrive here. They change nothing:
                    # returning while the kernel may still use the buffer is
                    # the one thing we must not do.
                    while not op.done:
                        try:
                            with CancelScope(shield=True):
                                await self._wait(op)
                        except cancelled:
                            pass
                # (Reached with the operation already complete when asyncio
                # cancels us during the yield above.)
                if late is not None and op.res >= 0:
                    late(op.res)
                raise
            return op.res
        finally:
            # A traceback keeps this frame alive; don't let it pin the buffer.
            keep = None

    # -- typed operations ---------------------------------------------

    async def openat(
        self, path: bytes, flags: int, mode: int = 0o666, *, blocking: bool = False
    ) -> int:
        """Open ``path``.

        The kernel first tries the open as if with ``O_NONBLOCK`` (which it
        then clears), and only on ``EAGAIN`` redoes it on a worker thread.
        For the few files where ``O_NONBLOCK`` changes what open(2) *means*
        rather than just whether it waits, ``blocking=True`` skips the first
        attempt.
        """
        buf = ctypes.create_string_buffer(path)
        res = await self.run(
            _uring.OP_OPENAT, _AT_FDCWD, 0, ctypes.addressof(buf), mode, flags, buf,
            os.close, _uring.SQE_ASYNC if blocking else 0,
        )  # fmt: skip
        if res < 0:
            raise OSError(-res, os.strerror(-res), os.fsdecode(path))
        return res

    async def close_fd(self, fd: int) -> None:
        _check(await self.run(_uring.OP_CLOSE, fd))

    async def poll(self, fd: int, events: int) -> int:
        """Wait until any of ``events`` (or an error or hangup) holds for
        ``fd``; return the ones that do, as a poll(2) mask."""
        if sys.byteorder == "big":  # the kernel wants the halves swapped
            events = (events & 0xFFFF) << 16 | events >> 16
        return _check(await self.run(_uring.OP_POLL_ADD, fd, 0, 0, 0, events))

    async def read(
        self,
        fd: int,
        buf: memoryview,
        late: Callable[[int], object] | None = None,
        offset: int = CUR_POS,
    ) -> int:
        """Read into a writable byte view; return the number of bytes read."""
        length = min(len(buf), MAX_RW)
        if not length:
            return 0
        addr, keep = writable_address(buf)
        try:
            while True:
                res = await self.run(_uring.OP_READ, fd, offset, addr, length, 0, keep, late)
                if res != _EINTR:  # as PEP 475 does for the plain syscalls
                    break
        finally:
            keep = None
        return res if res >= 0 else _check(res)

    async def write(
        self,
        fd: int,
        data: ReadableBuffer,
        late: Callable[[int], object] | None = None,
        offset: int = CUR_POS,
    ) -> int:
        """Write a bytes-like object; return the number of bytes written."""
        addr, length, keep = readable_address(data)
        length = min(length, MAX_RW)
        if not length:
            return 0
        try:
            while True:
                res = await self.run(_uring.OP_WRITE, fd, offset, addr, length, 0, keep, late)
                if res != _EINTR:  # as PEP 475 does for the plain syscalls
                    break
        finally:
            keep = None
        return res if res >= 0 else _check(res)

    async def fsync(self, fd: int, datasync: bool = False) -> None:
        flags = _uring.FSYNC_DATASYNC if datasync else 0
        _check(await self.run(_uring.OP_FSYNC, fd, 0, 0, 0, flags))

    async def ftruncate(self, fd: int, length: int) -> None:
        if _uring.OP_FTRUNCATE in self.supported:
            _check(await self.run(_uring.OP_FTRUNCATE, fd, length))
        else:  # kernels before 6.9
            await to_thread.run_sync(os.ftruncate, fd, length)


def _check(res: int) -> int:
    if res < 0:
        raise OSError(-res, os.strerror(-res))
    return res


_ki_protected = False


def _protect_from_trio_ki() -> None:
    """Keep Trio from raising KeyboardInterrupt in the middle of the ring.

    On Ctrl-C, Trio raises KeyboardInterrupt at whatever bytecode the running
    task has reached, unless that code is marked as protected, in which case
    it waits for the next checkpoint. Nothing here leaves the kernel holding
    a buffer we have forgotten if it is interrupted, but waiters could be
    left unwoken, and that would get in the way of the very shutdown the
    interrupt is asking for. (asyncio turns the first Ctrl-C into an ordinary
    cancellation of the main task, so needs nothing of the kind.)
    """
    global _ki_protected
    trio = sys.modules.get("trio")
    if _ki_protected or trio is None:
        return
    _ki_protected = True
    protect = trio.lowlevel.enable_ki_protection
    for cls, names in (
        (Driver, ("_complete", "_dispatch", "_submit", "_start", "_cancel", "_wait", "run",
                  "close")),
        (Ring, ("push", "unpush", "submit", "drain", "flush_overflow")),
    ):  # fmt: skip
        for name in names:
            setattr(cls, name, protect(getattr(cls, name)))


_current: RunVar[Driver] = RunVar("uringfile.driver")


def current_driver() -> Driver:
    """Return the running event loop's driver, creating it on first use."""
    try:
        driver = _current.get()
    except LookupError:
        driver = None
    if driver is None or driver.closed:
        driver = Driver()
        _current.set(driver)
    return driver


def _after_fork_in_child() -> None:
    # The child shares the parent's ring memory. Never touch it again; any
    # event loop that survives the fork gets a fresh ring on next use.
    for driver in list(_drivers):
        driver._inflight.clear()
        driver._driving = False
        # The loop's epoll instance is shared with the parent, and so is what
        # is registered in it: taking the eventfd out here would take it out
        # there. Just forget about it.
        driver._watcher, driver._watched = None, -1
        try:
            driver.close()
        except Exception:
            pass


os.register_at_fork(after_in_child=_after_fork_in_child)
