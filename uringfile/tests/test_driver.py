"""The bridge between the ring and the event loop."""

from __future__ import annotations

import asyncio
import errno
import gc
import os
import time

import anyio
import pytest

from uringfile import _driver, _uring, open_file
from uringfile._driver import Driver, current_driver

pytestmark = pytest.mark.anyio

asyncio_only = pytest.mark.parametrize(
    "anyio_backend",
    [("asyncio", {}), ("asyncio", {"use_uvloop": True})],
    indirect=True,
    ids=["asyncio", "uvloop"],
)


async def blocked_read(driver, rounds=1):
    """Reads that cannot complete until another task has had a turn."""
    r, w = os.pipe()
    try:
        buf = bytearray(1)
        for i in range(rounds):

            async def feed(byte=bytes([65 + i])):
                await anyio.sleep(0.002)
                os.write(w, byte)

            with anyio.fail_after(5):
                async with anyio.create_task_group() as tg:
                    tg.start_soon(feed)
                    assert await driver.read(r, memoryview(buf)) == 1
            assert buf[0] == 65 + i
    finally:
        os.close(r)
        os.close(w)


async def test_one_driver_per_event_loop():
    driver = current_driver()
    assert current_driver() is driver
    assert not driver.closed

    async def elsewhere():
        return current_driver()

    async with anyio.create_task_group() as tg:
        tg.start_soon(elsewhere)
    assert current_driver() is driver


def test_each_loop_gets_its_own_ring_and_gives_it_back(anyio_backend, count_fds, path):
    name, options = anyio_backend
    seen = []

    async def main():
        async with await open_file(path, "w") as f:
            await f.write("x")
        seen.append(id(current_driver()))

    before = count_fds()
    for _ in range(30):
        anyio.run(main, backend=name, backend_options=options)
    assert count_fds() == before  # (count_fds collects garbage first)


@pytest.mark.parametrize("shutdown", [True, False])
def test_asyncio_loop_frees_its_ring_without_waiting_for_gc(path, shutdown):
    async def main():
        async with await open_file(path, "w") as f:
            await f.write("x")

    gc.collect()
    gc.disable()
    try:
        before = len(os.listdir("/proc/self/fd"))
        for _ in range(5):
            loop = asyncio.new_event_loop()
            loop.run_until_complete(main())
            if shutdown:
                loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            del loop
            assert len(os.listdir("/proc/self/fd")) == before
    finally:
        gc.enable()


async def test_replaced_after_close():
    driver = current_driver()
    driver.close()
    with pytest.raises(RuntimeError, match="closed"):
        await driver.fsync(0)
    fresh = current_driver()
    assert fresh is not driver and not fresh.closed


async def test_many_waiters_one_eventfd(fifo):
    r, w = fifo
    driver = current_driver()
    got = []

    async def reader():
        buf = bytearray(1)
        n = await driver.read(r, memoryview(buf))
        got.append(bytes(buf[:n]))

    async with anyio.create_task_group() as tg:
        for _ in range(300):
            tg.start_soon(reader)
        await anyio.sleep(0.05)
        assert len(driver._inflight) == 300
        # One task sleeps on the eventfd; the others wait for it to tell them.
        assert driver._driving and len(driver._parked) == 299
        os.write(w, b"x" * 300)
    assert got == [b"x"] * 300
    assert not driver._inflight and not driver._parked and not driver._driving


async def test_completion_queue_overflow(fifo):
    """More completions arrive at once than the CQ has room for."""
    r, w = fifo
    driver = Driver(entries=1)
    try:
        assert driver._ring.cq_entries == 2
        got = []

        async def reader():
            buf = bytearray(1)
            n = await driver.read(r, memoryview(buf))
            got.append(bytes(buf[:n]))

        for round_ in range(3):
            async with anyio.create_task_group() as tg:
                for _ in range(64):
                    tg.start_soon(reader)
                await anyio.sleep(0.05)
                os.write(w, b"y" * 64)
        assert got == [b"y"] * 192
        assert not driver._inflight
    finally:
        driver.close()


async def test_inline_completions_still_share_the_loop(path, monkeypatch):
    """Back-to-back calls that the kernel answers on the spot do not yield
    every time, but they do yield."""
    with open(path, "wb") as f:
        f.write(bytes(4096))
    turns = 0
    stop = False

    async def other():
        nonlocal turns
        while not stop:
            await anyio.sleep(0)
            turns += 1

    async def hammer():
        nonlocal stop
        calls = 0
        async with await open_file(path, "rb", buffering=0) as f:
            deadline = time.monotonic() + 0.1
            while time.monotonic() < deadline:
                await f.seek(0)
                await f.read(4096)
                calls += 1
        stop = True
        return calls

    async with anyio.create_task_group() as tg:
        tg.start_soon(other)
        await anyio.sleep(0)
        start = turns
        calls = await hammer()
    during = turns - start
    assert calls > 500
    # 100 ms at one yield per half millisecond is 200; allow plenty of slack.
    assert during >= 20
    assert during < calls

    # With the interval at zero, every call is a full checkpoint.
    monkeypatch.setattr(_driver, "YIELD_INTERVAL", 0.0)
    stop, start = False, turns
    async with anyio.create_task_group() as tg:
        tg.start_soon(other)
        await anyio.sleep(0)
        start = turns
        calls = await hammer()
    assert turns - start >= calls


async def test_failed_submission_is_rolled_back(path, monkeypatch):
    driver = current_driver()
    async with await open_file(path, "w+b", buffering=0) as f:
        await f.write(b"abc")
        real = _uring.Ring.submit
        calls = 0

        def failing(self):
            nonlocal calls
            calls += 1
            raise OSError(errno.ENOMEM, "simulated")

        monkeypatch.setattr(_uring.Ring, "submit", failing)
        with pytest.raises(OSError, match="simulated"):
            await f.read(1)
        assert calls == 1
        assert not driver._inflight and driver._ring.pending == 0
        monkeypatch.setattr(_uring.Ring, "submit", real)
        await f.seek(0)
        assert await f.read() == b"abc"


async def test_transient_submission_failure_is_retried(path, monkeypatch):
    async with await open_file(path, "w+b", buffering=0) as f:
        real = _uring.Ring.submit
        failures = [errno.EBUSY, errno.EINTR, errno.EAGAIN]

        def flaky(self):
            if failures:
                err = failures.pop()
                raise OSError(err, os.strerror(err))
            return real(self)

        monkeypatch.setattr(_uring.Ring, "submit", flaky)
        assert await f.write(b"abc") == 3
        assert not failures


async def test_closing_a_ring_under_running_operations(fifo):
    r, _ = fifo
    driver = Driver()
    buf = bytearray(8)
    before = len(_driver._graveyard)
    outcomes = []

    async def read():
        try:
            await driver.read(r, memoryview(buf))
        except OSError as exc:
            outcomes.append(exc.errno)

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            for _ in range(3):  # one of them sleeps on the eventfd
                tg.start_soon(read)
            await anyio.sleep(0.02)
            assert len(driver._inflight) == 3
            efd = driver._efd
            driver.close()
    # Nobody is left waiting for an answer that cannot come...
    assert outcomes == [errno.ECANCELED] * 3
    with pytest.raises(OSError):
        os.fstat(efd)
    # ...and since the kernel may still write to the buffers, they stay
    # pinned for good.
    assert len(_driver._graveyard) == before + 3
    with pytest.raises(BufferError):
        buf.extend(b"x")


def test_fork(anyio_backend, path):
    """A forked child shares the parent's ring memory and must not use it."""
    name, options = anyio_backend
    with open(path, "w") as f:
        f.write("content")

    async def read():
        async with await open_file(path) as f:
            return await f.read()

    parent_driver = Driver()
    try:
        pid = os.fork()
        if pid == 0:
            code = 1
            try:
                assert parent_driver.closed
                # A fresh loop in the child gets a fresh ring and works.
                assert anyio.run(read, backend=name, backend_options=options) == "content"
                code = 0
            finally:
                os._exit(code)
        _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == 0
        # The parent's ring is unaffected.
        assert not parent_driver.closed

        async def nop():
            return await parent_driver.run(_uring.OP_NOP, -1)

        assert anyio.run(nop, backend=name, backend_options=options) == 0
    finally:
        parent_driver.close()
        gc.collect()


def test_worker_pool_does_not_depend_on_who_made_the_first_ring(tmp_path, anyio_backend):
    """Two FIFO opens each waiting for the other's file to show up need two
    kernel workers. A thread whose first ring was tiny would have one."""
    import threading

    name, options = anyio_backend
    a, b = tmp_path / "a", tmp_path / "b"
    os.mkfifo(a)
    os.mkfifo(b)
    result = []

    async def main():
        got = []

        async def reader(p):
            async with await open_file(p, "rb") as f:
                got.append(await f.read())

        async def writers():
            await anyio.sleep(0.1)  # both readers are parked in the kernel
            for p in (a, b):
                async with await open_file(p, "wb") as f:
                    await f.write(b"ok")

        with anyio.fail_after(10):
            async with anyio.create_task_group() as tg:
                tg.start_soon(reader, a)
                tg.start_soon(reader, b)
                tg.start_soon(writers)
        return got

    def thread():
        small = _uring.Ring(1)  # sizes this thread's worker pool at one
        try:
            result.append(anyio.run(main, backend=name, backend_options=options))
        except BaseException as exc:
            result.append(exc)
        finally:
            small.close()

    t = threading.Thread(target=thread)
    t.start()
    t.join()
    assert result == [[b"ok", b"ok"]]


async def test_interrupt_just_after_the_kernel_took_a_request(fifo, monkeypatch):
    """An exception (think: a signal handler's) surfacing right as
    io_uring_enter returns must not make us forget a request the kernel
    now has, nor rewind the queue past what it consumed."""
    r, w = fifo
    driver = current_driver()
    real = _uring.Ring.submit
    armed = True

    def submit(self):
        nonlocal armed
        n = real(self)
        if armed:
            armed = False
            raise KeyboardInterrupt
        return n

    monkeypatch.setattr(_uring.Ring, "submit", submit)
    buf = bytearray(4)
    with pytest.raises(KeyboardInterrupt):
        await driver.read(r, memoryview(buf))
    # The read is in the kernel: still tracked, buffer still pinned.
    assert len(driver._inflight) == 1
    assert driver._ring.pending == 0
    with pytest.raises(BufferError):
        buf.extend(b"x")
    # The ring is not wedged: later operations go through, and the orphan's
    # completion is collected along the way.
    os.write(w, b"abcdWXYZ")
    other = bytearray(4)
    with anyio.fail_after(5):
        assert await driver.read(r, memoryview(other)) == 4
    assert bytes(buf) == b"abcd" and bytes(other) == b"WXYZ"
    assert not driver._inflight
    buf.extend(b"x")


async def test_interrupt_while_dispatching_completions(fifo, monkeypatch):
    r, w = fifo
    driver = current_driver()
    bufs = [bytearray(1) for _ in range(4)]
    ops = []
    for buf in bufs:
        addr, keep = _uring.writable_address(memoryview(buf))
        ops.append(driver._start(_uring.OP_READ, r, _uring.CUR_POS, addr, 1, 0, keep))
    assert not any(op.done for op in ops)
    os.write(w, b"wxyz")

    real = Driver._complete
    calls = 0

    def complete(self, user_data, res):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt  # with the second completion half handled
        real(self, user_data, res)

    monkeypatch.setattr(Driver, "_complete", complete)
    with pytest.raises(KeyboardInterrupt):
        with anyio.fail_after(5):
            while True:
                await anyio.sleep(0.01)
                driver._dispatch()
    monkeypatch.setattr(Driver, "_complete", real)
    with anyio.fail_after(5):
        while not all(op.done for op in ops):
            await anyio.sleep(0.01)
            driver._dispatch()  # picks up exactly where it was cut off
    assert [op.res for op in ops] == [1, 1, 1, 1]
    assert sorted(map(bytes, bufs)) == [b"w", b"x", b"y", b"z"]
    assert not driver._inflight


@pytest.mark.parametrize("anyio_backend", [("trio", {})], indirect=True, ids=["trio"])
async def test_trio_keyboard_interrupt_protection(monkeypatch, path):
    """Under Trio, Ctrl-C may not land in the middle of the ring's bookkeeping."""
    import trio

    seen = []
    real = _uring.Ring.push

    def push(self, *args):
        seen.append(trio.lowlevel.currently_ki_protected())
        return real(self, *args)

    assert not trio.lowlevel.currently_ki_protected()
    monkeypatch.setattr(_uring.Ring, "push", push)
    async with await open_file(path, "w") as f:
        await f.write("x")
    assert seen and all(seen)


# -- asyncio: one reader on the eventfd for the life of the ring ---------------


@asyncio_only
async def test_asyncio_registers_the_eventfd_once(monkeypatch):
    loop = asyncio.get_running_loop()
    calls = []
    add, remove = loop.add_reader, loop.remove_reader
    monkeypatch.setattr(loop, "add_reader", lambda fd, *a: (calls.append(("add", fd)), add(fd, *a)))
    monkeypatch.setattr(loop, "remove_reader", lambda fd: (calls.append(("rm", fd)), remove(fd))[1])
    driver = Driver()
    efd = driver._efd
    try:
        await blocked_read(driver, rounds=20)
        assert calls == [("add", efd)]
    finally:
        driver.close()
    # Taken out again before the descriptor is closed: a loop that keeps a
    # reader for a dead descriptor chokes when the number comes round again.
    assert calls == [("add", efd), ("rm", efd)]
    assert not remove(efd)
    with pytest.raises(OSError):
        os.fstat(efd)


@asyncio_only
async def test_a_signalled_eventfd_does_not_keep_the_loop_awake(monkeypatch):
    """Operations that complete on the spot signal the eventfd too, with
    nobody waiting for it. The loop must not be woken by that forever."""
    seen = 0
    real = Driver._on_signal

    def on_signal(self):
        nonlocal seen
        seen += 1
        real(self)

    monkeypatch.setattr(Driver, "_on_signal", on_signal)
    driver = Driver()
    try:
        await blocked_read(driver)  # the reader is in place from here on
        await asyncio.sleep(0.01)
        seen = 0
        for _ in range(10):
            assert await driver.run(_uring.OP_NOP, -1) == 0
        assert os.eventfd_read(driver._efd) > 0  # signalled, as promised...
        os.eventfd_write(driver._efd, 1)  # ...so put that back
        await asyncio.sleep(0.05)
        # Once for what is in it now, and (depending on the order in which
        # the loop does things) once during the yield of the first no-op.
        assert 1 <= seen <= 2
    finally:
        driver.close()


@asyncio_only
async def test_fork_leaves_the_parents_reader_alone():
    """A forked child closes its copy of the ring. The loop's epoll instance
    is shared with the parent, so it must not unregister anything from it."""
    import warnings

    driver = current_driver()
    await blocked_read(driver)
    assert driver._watcher is not None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)  # fork with threads about
        pid = os.fork()
    if pid == 0:
        os._exit(0 if driver.closed else 1)  # (the at-fork hook has run)
    _, status = os.waitpid(pid, 0)  # noqa: ASYNC222
    assert os.waitstatus_to_exitcode(status) == 0
    assert not driver.closed
    await blocked_read(driver, rounds=3)


def test_one_ring_in_several_loops(anyio_backend):
    """Not something current_driver() ever does, but a ring is not tied to
    the loop it was first used in."""
    name, options = anyio_backend
    driver = Driver()
    try:
        for _ in range(3):
            anyio.run(blocked_read, driver, 3, backend=name, backend_options=options)
    finally:
        driver.close()


@asyncio_only
async def test_asyncio_loop_without_add_reader(monkeypatch):
    """Loops that cannot watch descriptors get anyio's way of doing it."""
    loop = asyncio.get_running_loop()
    real = loop.add_reader
    refused = 0

    def add_reader(fd, *args):
        nonlocal refused
        if fd == driver._efd and args[0].__name__ == "_on_signal":
            refused += 1
            raise NotImplementedError
        return real(fd, *args)

    driver = Driver()
    monkeypatch.setattr(loop, "add_reader", add_reader)
    try:
        await blocked_read(driver, rounds=3)
        assert refused == 3 and driver._watcher is None
    finally:
        driver.close()
