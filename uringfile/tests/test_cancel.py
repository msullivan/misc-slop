"""Cancellation: prompt, and never at the cost of data."""

from __future__ import annotations

import asyncio
import fcntl
import os
import sys
import time

import anyio
import pytest

from uringfile import open_file
from uringfile._driver import Driver, current_driver

pytestmark = pytest.mark.anyio

PIPE_SIZE = 4096


@pytest.fixture
def uncancellable(monkeypatch):
    """Make the kernel ignore cancel requests.

    That is what happens for real when an operation is already executing
    somewhere it cannot be interrupted (a disk read in progress, say): the
    caller is cancelled, and then the operation completes anyway. Pipes
    give us the same race on demand.
    """
    monkeypatch.setattr(Driver, "_cancel", lambda self, op: None)


@pytest.fixture
def full_pipe(fifo):
    """A pipe with no room left in it: ``(read_fd, write_fd, contents)``."""
    r, w = fifo
    fcntl.fcntl(w, fcntl.F_SETPIPE_SZ, PIPE_SIZE)
    os.set_blocking(w, False)
    filler = b""
    try:
        while True:
            filler += b"." * os.write(w, b"." * 1024)
    except BlockingIOError:
        pass
    os.set_blocking(w, True)
    return r, w, filler


def drain(fd, n):
    out = b""
    while len(out) < n:
        chunk = os.read(fd, n - len(out))
        assert chunk
        out += chunk
    return out


def read_available(fd):
    os.set_blocking(fd, False)
    out = b""
    try:
        while chunk := os.read(fd, 65536):
            out += chunk
    except BlockingIOError:
        pass
    os.set_blocking(fd, True)
    return out


async def later(delay, fn, *args):
    await anyio.sleep(delay)
    fn(*args)


# -- reads ------------------------------------------------------------------


@pytest.mark.parametrize("buffering", [0, -1])
async def test_blocked_read_is_cancelled_promptly(fifo, buffering):
    r, w = fifo
    async with await open_file(r, "rb", buffering=buffering, closefd=False) as f:
        start = time.monotonic()
        with anyio.move_on_after(0.05) as scope:
            await f.read(1)
        assert scope.cancelled_caught
        assert time.monotonic() - start < 1
        assert not current_driver()._inflight  # the kernel let go of it
        os.write(w, b"x")
        assert await f.read(1) == b"x"


async def test_already_cancelled_scope_submits_nothing(fifo):
    r, _ = fifo
    async with await open_file(r, "rb", closefd=False) as f:
        driver = current_driver()
        before = driver._seq
        with anyio.CancelScope() as scope:
            scope.cancel()
            await f.read(1)
        assert scope.cancelled_caught
        assert driver._seq == before


@pytest.mark.parametrize(
    "call, expected",
    [
        (lambda f: f.read(10), b"abcdefgh\ni"),
        (lambda f: f.readline(), b"abcdefgh\n"),
        (lambda f: f.readinto(bytearray(10)), 10),
        (lambda f: f.read(), b"abcdefgh\nij"),
        (lambda f: f.readlines(), [b"abcdefgh\n", b"ij"]),
    ],
)
@pytest.mark.parametrize("buffering", [4, -1])
async def test_cancelled_read_keeps_what_it_had(fifo, buffering, call, expected):
    """A multi-step read is interrupted half way. Nothing may be lost: the
    same call, repeated, sees the stream as if the first never happened."""
    r, w = fifo
    async with await open_file(r, "rb", buffering=buffering, closefd=False) as f:
        os.write(w, b"abcd")
        with anyio.move_on_after(0.05) as scope:
            await call(f)
        assert scope.cancelled_caught
        os.write(w, b"efgh\nij")
        os.close(w)
        assert await call(f) == expected


async def test_cancelled_unbuffered_readall_and_readline_keep_data(fifo):
    r, w = fifo
    async with await open_file(r, "rb", buffering=0, closefd=False) as f:
        os.write(w, b"ab")
        with anyio.move_on_after(0.05) as scope:
            await f.readline()
        assert scope.cancelled_caught
        os.write(w, b"c\nde")
        assert await f.readline() == b"abc\n"
        with anyio.move_on_after(0.05) as scope:
            await f.read()
        assert scope.cancelled_caught
        os.write(w, b"f")
        os.close(w)
        assert await f.read() == b"def"


@pytest.mark.parametrize(
    "call, expected",
    [
        (lambda f: f.read(6), "日本語にほん"),
        (lambda f: f.readline(), "日本語にほ\n"),
        (lambda f: f.read(), "日本語にほんご"),
    ],
)
async def test_cancelled_text_read_keeps_what_it_had(fifo, call, expected):
    r, w = fifo
    data = "日本語にほんご".encode()
    if "\n" in expected:
        data = "日本語にほ\nんご".encode()
    async with await open_file(r, encoding="utf-8", closefd=False) as f:
        os.write(w, data[:7])  # two characters and a third of the next
        with anyio.move_on_after(0.05) as scope:
            await call(f)
        assert scope.cancelled_caught
        os.write(w, data[7:])
        os.close(w)
        assert await call(f) == expected


# -- reads that complete after their caller was cancelled -------------------


async def test_late_unbuffered_read_is_kept(fifo, uncancellable):
    r, w = fifo
    async with await open_file(r, "rb", buffering=0, closefd=False) as f:
        async with anyio.create_task_group() as tg:
            tg.start_soon(later, 0.1, os.write, w, b"late")
            with anyio.move_on_after(0.02) as scope:
                # The kernel answered after all: that is the result, and
                # only once it had answered.
                assert await f.read(10) == b"late"
                assert not current_driver()._inflight
                # The cancellation itself is not lost, just put off.
                await anyio.sleep(1)
                pytest.fail("not cancelled")
            assert scope.cancelled_caught
        os.write(w, b"r")
        assert await f.read(10) == b"r"


@pytest.mark.parametrize(
    "call, first, second",
    [
        # Done in one read: those return what it got.
        (lambda f: f.read(3), b"lat", b"e!"),
        (lambda f: f.read1(10_000), b"late", b"!"),
        (lambda f: f.peek(), b"late", b"late"),
        # Wanting more, they go back for it, and are cancelled there.
        (lambda f: f.read(10_000), None, b"late!"),
        (lambda f: f.readline(), None, b"late!"),
        (lambda f: f.readinto(bytearray(10_000)), None, 5),
        (lambda f: f.read(), None, b"late!"),
    ],
)
async def test_late_buffered_read_is_kept(fifo, uncancellable, call, first, second):
    r, w = fifo
    async with await open_file(r, "rb", closefd=False) as f:
        async with anyio.create_task_group() as tg:
            tg.start_soon(later, 0.1, os.write, w, b"late")
            got = None
            with anyio.move_on_after(0.02) as scope:
                got = await call(f)
            assert scope.cancel_called
            assert got == first
            assert scope.cancelled_caught == (first is None)
        os.write(w, b"!")
        os.close(w)
        assert await call(f) == second


async def test_late_text_read_is_kept(fifo, uncancellable):
    r, w = fifo
    async with await open_file(r, encoding="utf-8", closefd=False) as f:
        async with anyio.create_task_group() as tg:
            tg.start_soon(later, 0.1, os.write, w, "é\nà".encode())
            with anyio.move_on_after(0.02) as scope:
                assert await f.readline() == "é\n"
            assert scope.cancel_called and not scope.cancelled_caught
        os.close(w)
        assert await f.read() == "à"


# -- writes -----------------------------------------------------------------


async def test_cancelled_small_write_is_not_taken(full_pipe):
    r, w, filler = full_pipe
    async with await open_file(w, "wb", buffering=16, closefd=False) as f:
        assert await f.write(b"A" * 10) == 10  # fits in the buffer
        with anyio.move_on_after(0.05) as scope:
            await f.write(b"B" * 10)  # has to flush first, and cannot
        assert scope.cancelled_caught
        assert drain(r, len(filler)) == filler
        await f.flush()
        assert read_available(r) == b"A" * 10  # no B: that write did not happen


async def test_cancelled_large_write_stays_buffered(full_pipe):
    r, w, filler = full_pipe
    async with await open_file(w, "wb", buffering=16, closefd=False) as f:
        with anyio.move_on_after(0.05) as scope:
            await f.write(b"C" * 100)
        assert scope.cancelled_caught
        assert drain(r, len(filler)) == filler
        await f.flush()
        assert read_available(r) == b"C" * 100  # all of it, once


async def test_cancelled_flush_can_be_retried(full_pipe):
    r, w, filler = full_pipe
    async with await open_file(w, "wb", closefd=False) as f:
        await f.write(b"D" * 100)
        for _ in range(3):
            with anyio.move_on_after(0.02) as scope:
                await f.flush()
            assert scope.cancelled_caught
        assert drain(r, len(filler)) == filler
        await f.flush()
        assert read_available(r) == b"D" * 100


async def test_late_write_is_not_repeated(full_pipe, uncancellable):
    r, w, filler = full_pipe
    payload = bytes(range(256)) * 40  # 10240 bytes: several pipefuls
    got = []
    async with await open_file(w, "wb", buffering=64, closefd=False) as f:
        async with anyio.create_task_group() as tg:
            # Make room after the writer has been cancelled, so that its
            # write goes through with nobody waiting for the result.
            tg.start_soon(later, 0.1, lambda: got.append(drain(r, len(filler) + 100)))
            with anyio.move_on_after(0.02) as scope:
                await f.write(payload)
            assert scope.cancelled_caught

        async def reader():
            while sum(map(len, got)) < len(filler) + len(payload):
                got.append(await anyio.to_thread.run_sync(os.read, r, 65536))

        async with anyio.create_task_group() as tg:
            tg.start_soon(reader)
            await f.flush()
    assert b"".join(got) == filler + payload


async def test_late_unbuffered_write_reports_its_count(full_pipe, uncancellable):
    r, w, filler = full_pipe
    async with await open_file(w, "wb", buffering=0, closefd=False) as f:
        async with anyio.create_task_group() as tg:
            tg.start_soon(later, 0.1, drain, r, len(filler))
            with anyio.move_on_after(0.02) as scope:
                n = await f.write(b"W" * 100)
            assert scope.cancel_called and not scope.cancelled_caught
        assert n == 100
        assert read_available(r) == b"W" * 100


async def test_cancelled_text_write(full_pipe):
    r, w, filler = full_pipe
    async with await open_file(w, "w", buffering=16, closefd=False, newline="\n") as f:
        await f.write("short\n")
        with anyio.move_on_after(0.05) as scope:
            await f.write("this one does not fit in the buffer\n")
        assert scope.cancelled_caught
        assert drain(r, len(filler)) == filler
        await f.flush()
        out = read_available(r)
    # The first line exactly once; the second all or nothing.
    assert out in (b"short\n", b"short\nthis one does not fit in the buffer\n")


# -- open and close ---------------------------------------------------------


@pytest.mark.parametrize("mode", ["rb", "wb", "r", "a"])
async def test_opening_a_fifo_with_no_peer_can_be_cancelled(tmp_path, mode, count_fds):
    """open(2) on a FIFO blocks until the other end shows up. A thread stuck
    there cannot be interrupted; the ring can."""
    p = tmp_path / "fifo"
    os.mkfifo(p)
    async with await open_file(tmp_path / "warmup", "w"):
        pass
    before = count_fds()
    start = time.monotonic()
    with anyio.move_on_after(0.05) as scope:
        await open_file(p, mode)
    assert scope.cancelled_caught
    assert time.monotonic() - start < 1
    assert count_fds() == before


async def test_fifo_open_waits_for_the_other_end(tmp_path):
    """The kernel's first, non-blocking attempt at an open would hand back a
    read end with no writer, on which the first read reports end of file.
    open() semantics are: wait for the writer."""
    p = tmp_path / "fifo"
    os.mkfifo(p)
    order = []

    async def reader():
        async with await open_file(p, "rb") as f:
            order.append("reader open")
            order.append(await f.read())

    async def writer():
        await anyio.sleep(0.05)
        order.append("writer opening")
        async with await open_file(p, "wb") as f:
            await f.write(b"hello")

    async with anyio.create_task_group() as tg:
        tg.start_soon(reader)
        tg.start_soon(writer)
    assert order == ["writer opening", "reader open", b"hello"]


async def test_fifo_writer_first(tmp_path):
    p = tmp_path / "fifo"
    os.mkfifo(p)
    got = []

    async def writer():
        async with await open_file(p, "w") as f:
            got.append("writer open")
            await f.write("hi\n")

    async def reader():
        await anyio.sleep(0.05)
        got.append("reader opening")
        async with await open_file(p) as f:
            got.append(await f.readline())

    async with anyio.create_task_group() as tg:
        tg.start_soon(writer)
        tg.start_soon(reader)
    assert got == ["reader opening", "writer open", "hi\n"]


async def test_late_open_does_not_leak_the_descriptor(tmp_path, uncancellable, count_fds):
    p = tmp_path / "fifo"
    os.mkfifo(p)
    async with await open_file(tmp_path / "warmup", "w"):
        pass
    before = count_fds()

    def writer_comes_and_goes():
        os.close(os.open(p, os.O_WRONLY | os.O_NONBLOCK))

    async with anyio.create_task_group() as tg:
        # The open is cancelled first and completes afterwards.
        tg.start_soon(later, 0.1, writer_comes_and_goes)
        with anyio.move_on_after(0.02) as scope:
            # Whether this is cancelled, or completes after all, depends on
            # which of its steps the kernel was in.
            f = await open_file(p, "rb")
            await f.aclose()
        assert scope.cancel_called
    assert count_fds() == before


async def test_fifo_writer_that_leaves_before_we_look(tmp_path):
    """Our first, non-blocking open is what lets a waiting writer in. If it
    has written and gone by the time we go to wait for it, its data must
    still be found, not waited for forever."""
    import subprocess
    import sys

    p = tmp_path / "fifo"
    os.mkfifo(p)
    code = "import sys; f = open(sys.argv[1], 'wb'); f.write(b'quick'); f.close()"
    proc = subprocess.Popen([sys.executable, "-c", code, str(p)])
    try:
        await anyio.sleep(0.3)  # it is now blocked in open(), waiting for us
        with anyio.fail_after(5):
            async with await open_file(p, "rb") as f:
                assert await f.read() == b"quick"
    finally:
        proc.wait(5)


async def test_unlinked_fifo(tmp_path):
    p = tmp_path / "fifo"
    os.mkfifo(p)
    writer = os.open(p, os.O_RDWR)  # keeps it "connected"
    try:
        async with await open_file(p, "rb") as f:
            os.unlink(p)
            os.write(writer, b"x")
            assert await f.read(1) == b"x"
    finally:
        os.close(writer)


async def test_cancelled_aclose_still_closes(full_pipe):
    r, w, filler = full_pipe
    f = await open_file(w, "wb")
    fd = f.fileno()
    await f.write(b"never arrives")
    with anyio.move_on_after(0.05) as scope:
        await f.aclose()  # the flush cannot make progress
    assert scope.cancelled_caught
    assert f.closed
    with pytest.raises(OSError):
        os.fstat(fd)
    assert drain(r, len(filler)) == filler
    assert os.read(r, 10) == b""  # EOF: the write end really is closed


async def test_cancelled_aclose_of_a_busy_file_closes_it_anyway(fifo):
    r, w = fifo
    f = await open_file(r, "rb")
    fd = f.fileno()
    async with anyio.create_task_group() as tg:
        tg.start_soon(f.read, 1)  # holds the file, blocked
        await anyio.sleep(0.02)
        with anyio.move_on_after(0.05) as scope:
            await f.aclose()  # waits its turn; gives up
        assert scope.cancelled_caught
        assert f.closed
        with pytest.raises(OSError):
            os.fstat(fd)
        tg.cancel_scope.cancel()


async def test_exception_in_context_manager_closes(path):
    with pytest.raises(ZeroDivisionError):
        async with await open_file(path, "w") as f:
            await f.write("kept")
            1 / 0
    assert f.closed
    with open(path) as g:
        assert g.read() == "kept"


# -- tasks sharing a file, and tasks sharing the ring ------------------------


async def test_cancelling_a_task_waiting_for_the_file(fifo):
    r, w = fifo
    results = []
    async with await open_file(r, "rb", closefd=False) as f:
        async with anyio.create_task_group() as tg:

            async def reader(tag):
                results.append((tag, await f.read(1)))

            tg.start_soon(reader, "first")
            await anyio.sleep(0.02)
            with anyio.move_on_after(0.05) as scope:
                await f.read(1)  # queued behind the first reader
            assert scope.cancelled_caught
            tg.start_soon(reader, "second")
            await anyio.sleep(0.02)
            os.write(w, b"xy")
    assert sorted(results) == [("first", b"x"), ("second", b"y")]


async def test_cancelling_the_task_that_holds_the_file(fifo):
    r, w = fifo
    got = []
    async with await open_file(r, "rb", closefd=False) as f:
        async with anyio.create_task_group() as tg:
            holder = anyio.CancelScope()

            async def first():
                with holder:
                    await f.read(1)
                got.append("first cancelled")

            async def second():
                got.append(await f.read(1))

            tg.start_soon(first)
            await anyio.sleep(0.02)
            tg.start_soon(second)  # queued behind the first
            await anyio.sleep(0.02)
            holder.cancel()
            await anyio.sleep(0.02)
            os.write(w, b"z")
    assert got == ["first cancelled", b"z"]


async def test_cancelling_the_task_that_drives_the_ring(fifo, tmp_path):
    """Whoever sleeps on the eventfd does so on behalf of every waiter. If
    that task is cancelled, another must take over."""
    r, w = fifo
    r2, w2 = os.pipe()
    try:
        async with (
            await open_file(r, "rb", closefd=False) as a,
            await open_file(r2, "rb", closefd=False) as b,
        ):
            got = []
            async with anyio.create_task_group() as tg:

                async def driver_then_cancelled():
                    with anyio.move_on_after(0.05):
                        await a.read(1)
                    got.append("cancelled")

                async def follower(i):
                    got.append(await b.read(1))

                tg.start_soon(driver_then_cancelled)
                await anyio.sleep(0.01)
                for i in range(3):
                    tg.start_soon(follower, i)
                await anyio.sleep(0.1)
                assert got == ["cancelled"]
                os.write(w2, b"abc")
            assert sorted(got[1:]) == [b"a", b"b", b"c"]
    finally:
        os.close(r2)
        os.close(w2)


# -- asyncio's own cancellation, with no cancel scope involved ---------------


@pytest.mark.parametrize("anyio_backend", [("asyncio", {})], indirect=True, ids=["asyncio"])
async def test_native_task_cancel(fifo):
    r, w = fifo
    async with await open_file(r, "rb", closefd=False) as f:
        os.write(w, b"ab")
        task = asyncio.ensure_future(f.read(4))
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not current_driver()._inflight
        os.write(w, b"cd")
        assert await f.read(4) == b"abcd"


@pytest.mark.parametrize("anyio_backend", [("asyncio", {})], indirect=True, ids=["asyncio"])
async def test_native_timeout(fifo):
    r, _ = fifo
    async with await open_file(r, "rb", closefd=False) as f:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(f.read(1), 0.05)


async def native_cancel(coro, times=1, gap=0.02):
    """Run ``coro`` as a task and cancel it the asyncio way, ``times`` times."""
    task = asyncio.ensure_future(coro)
    for _ in range(times):
        await asyncio.sleep(gap)
        task.cancel()
    try:
        return await task
    except asyncio.CancelledError:
        return "cancelled"


asyncio_only = pytest.mark.parametrize(
    "anyio_backend",
    [("asyncio", {}), ("asyncio", {"use_uvloop": True})],
    indirect=True,
    ids=["asyncio", "uvloop"],
)


@asyncio_only
async def test_native_cancel_cannot_abandon_an_operation(fifo, uncancellable):
    """Task.cancel() goes straight through an anyio shield. Cancelling twice
    must still not hand the buffer back while the kernel can write to it."""
    r, w = fifo
    driver = current_driver()
    async with await open_file(r, "rb", buffering=0, closefd=False) as f:
        buf = bytearray(8)
        async with anyio.create_task_group() as tg:
            tg.start_soon(later, 0.15, os.write, w, b"late")
            assert await native_cancel(f.readinto(buf), times=3) == "cancelled"
        # By the time the caller is told, the kernel is done with the buffer.
        assert not driver._inflight
        buf.extend(b"resizable again")
        os.write(w, b"r")
        assert await f.read(10) == b"late"  # and nothing was lost
        assert await f.read(10) == b"r"


@asyncio_only
async def test_native_cancel_during_buffered_read(fifo, uncancellable):
    r, w = fifo
    async with await open_file(r, "rb", closefd=False) as f:
        async with anyio.create_task_group() as tg:
            tg.start_soon(later, 0.15, os.write, w, b"abcd")
            assert await native_cancel(f.read(4), times=2) == "cancelled"
        os.write(w, b"efgh")
        os.close(w)
        assert await f.read() == b"abcdefgh"


@asyncio_only
async def test_native_cancel_during_flush(full_pipe, uncancellable):
    r, w, filler = full_pipe
    async with await open_file(w, "wb", closefd=False) as f:
        await f.write(b"hello")
        async with anyio.create_task_group() as tg:
            tg.start_soon(later, 0.15, lambda: drain(r, len(filler)))
            assert await native_cancel(f.flush(), times=2) == "cancelled"
        await f.flush()
        assert read_available(r) == b"hello"  # once


needs_rearm = pytest.mark.skipif(
    sys.version_info < (3, 13), reason="asyncio cancellation is only put back from 3.13"
)


@asyncio_only
@needs_rearm
async def test_native_cancel_of_a_late_unbuffered_write(full_pipe, uncancellable):
    """asyncio's cancellation, unlike anyio's, is not raised again by itself.
    A write that went through anyway still reports its count, and the
    cancellation is put back for the next await."""
    r, w, filler = full_pipe
    got = []
    async with await open_file(w, "wb", buffering=0, closefd=False) as f:

        async def writer():
            got.append(await f.write(b"W" * 100))
            await asyncio.sleep(1)
            got.append("not cancelled")

        async with anyio.create_task_group() as tg:
            tg.start_soon(later, 0.15, drain, r, len(filler))
            assert await native_cancel(writer(), times=2) == "cancelled"
    assert got == [100]
    assert read_available(r) == b"W" * 100


@asyncio_only
@needs_rearm
async def test_timeout_around_a_late_write(full_pipe, uncancellable):
    """The timeout's block finished; it takes its cancellation back, and
    nothing is left over to cancel the task later."""
    r, w, filler = full_pipe
    async with await open_file(w, "wb", buffering=0, closefd=False) as f:
        async with anyio.create_task_group() as tg:
            tg.start_soon(later, 0.1, drain, r, len(filler))
            async with asyncio.timeout(0.02):
                n = await f.write(b"T" * 100)
        assert n == 100
        await asyncio.sleep(0.01)  # not cancelled
        assert asyncio.current_task().cancelling() == 0
    assert read_available(r) == b"T" * 100


@asyncio_only
async def test_native_cancel_of_a_small_write_whose_flush_was_late(full_pipe, uncancellable):
    """The flush that makes room goes through; the write is still not taken."""
    r, w, filler = full_pipe
    async with await open_file(w, "wb", buffering=16, closefd=False) as f:
        await f.write(b"A" * 10)
        async with anyio.create_task_group() as tg:
            tg.start_soon(later, 0.15, drain, r, len(filler))
            assert await native_cancel(f.write(b"B" * 10), times=2) == "cancelled"
        await f.flush()
        assert read_available(r) == b"A" * 10


@asyncio_only
async def test_native_cancel_of_an_operation_that_completed_inline(
    tmp_path, monkeypatch, fifo, count_fds
):
    """Operations the kernel answers on the spot still yield now and then,
    and asyncio can cancel the task right there, with the result in hand."""
    from uringfile import _driver

    monkeypatch.setattr(_driver, "YIELD_INTERVAL", 0.0)  # yield every time

    async def cancelled_at_once(coro):
        task = asyncio.ensure_future(coro)
        await asyncio.sleep(0)  # it submits, completes inline, yields
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    r, w = fifo
    for buffering in (0, -1):
        os.write(w, b"AAAA")
        async with await open_file(r, "rb", buffering=buffering, closefd=False) as f:
            await cancelled_at_once(f.read(4))
            os.write(w, b"BBBB")
            with anyio.fail_after(5):  # (were the first four lost, we would wait)
                assert await f.read(4) + await f.read(4) == b"AAAABBBB"

    async with await open_file(w, "wb", closefd=False) as f:
        await f.write(b"hello")
        await cancelled_at_once(f.flush())
        await f.flush()
    assert os.read(r, 100) == b"hello"

    (tmp_path / "f").write_bytes(b"")
    before = count_fds()
    await cancelled_at_once(open_file(tmp_path / "f"))
    assert count_fds() == before


async def test_cancelled_text_write_does_not_disturb_the_encoder(full_pipe):
    """A stateful encoding: the bytes for a write that is then not taken
    must not leave the encoder believing they were sent."""
    r, w, filler = full_pipe
    f = await open_file(w, "w", encoding="iso2022_jp", buffering=8, closefd=False)
    await f.write("abc")
    outcomes = []
    for _ in range(2):
        with anyio.move_on_after(0.03) as scope:
            await f.write("日本")  # has to flush "abc" first, and cannot
        outcomes.append(scope.cancelled_caught)
    assert drain(r, len(filler)) == filler
    await f.write("日本")
    await f.aclose()  # (closing ends the shifted run)
    out = read_available(r)
    assert outcomes == [True, True]
    assert out.decode("iso2022_jp") == "abc日本"
    assert out.startswith(b"abc\x1b$B")  # the shift sequence is there


async def test_utf16_bom_survives_a_cancelled_first_write(full_pipe):
    r, w, filler = full_pipe
    async with await open_file(w, "w", encoding="utf-16", buffering=8, closefd=False) as f:
        with anyio.move_on_after(0.03) as scope:
            await f.write("x" * 100)  # taken; its flush is what is cancelled
        assert scope.cancelled_caught
        assert drain(r, len(filler)) == filler
        await f.write("y")
        await f.flush()
        assert read_available(r).decode("utf-16") == "x" * 100 + "y"


async def test_unbuffered_write_after_a_late_read(path, uncancellable, monkeypatch):
    """Bytes a cancelled read delivered late are kept for the next read, and
    the position reported is the one before them. A write must agree."""
    with open(path, "wb") as g:
        g.write(b"0123456789")
    async with await open_file(path, "r+b", buffering=0) as f:
        # Stand in for a read that completes after its caller was cancelled.
        f._raw._stash = os.read(f.fileno(), 4)
        assert await f.tell() == 0
        assert await f.write(b"XY") == 2
        assert await f.tell() == 2
        assert await f.read() == b"23456789"
    with open(path, "rb") as g:
        assert g.read() == b"XY23456789"


async def test_aclose_under_cancellation_keeps_a_regular_files_data(path):
    with anyio.CancelScope() as scope:
        async with await open_file(path, "w") as f:
            await f.write("important\n")
            scope.cancel()
            await anyio.sleep(1)
    assert scope.cancelled_caught
    assert f.closed
    with open(path) as g:
        assert g.read() == "important\n"

    # Also when aclose() is itself what gets cancelled.
    f = await open_file(path, "wb")
    await f.write(b"x" * 100_000)
    with anyio.CancelScope() as scope:
        scope.cancel()
        await f.aclose()
    assert scope.cancelled_caught and f.closed
    assert os.path.getsize(path) == 100_000


async def test_cancelled_text_seek_did_not_happen(fifo, tmp_path, monkeypatch):
    p = tmp_path / "f"
    text = "+AGEAYgBj-" * 20  # UTF-7: runs that only decode as a whole
    p.write_bytes(text.encode("ascii"))
    async with await open_file(p, encoding="utf-7") as f:
        whole = await f.read()
        await f.seek(0)
        await f.read(10)
        target = await f.tell()
        await f.seek(0)
        assert await f.read(15) == whole[:15]
        here = await f.tell()

        # Make the read that a seek to `target` needs get cancelled.
        buffer = f._impl.buffer
        real = buffer.read

        async def cancelled_read(n):
            raise anyio.get_cancelled_exc_class()() if False else KeyboardInterrupt

        monkeypatch.setattr(buffer, "read", cancelled_read)
        if _unpack(target)[3]:  # only meaningful if the cookie needs a re-read
            with pytest.raises(KeyboardInterrupt):
                await f.seek(target)
            monkeypatch.setattr(buffer, "read", real)
            assert await f.tell() == here
            assert await f.read(5) == whole[15:20]


def _unpack(cookie):
    from uringfile._io import _unpack_cookie

    return _unpack_cookie(cookie)


async def test_huge_descriptor_number():
    driver = current_driver()
    for call in (lambda: open(2**31), lambda: open_file(2**31)):
        with pytest.raises(TypeError, match="not int"):
            result = call()
            await result if hasattr(result, "__await__") else result.close()
    assert not driver._inflight


async def test_fifo_wait_reports_a_failed_reopen(tmp_path, monkeypatch, count_fds):
    """Running out of descriptors while waiting for a FIFO's writer is an
    error, not a reason to pretend the writer showed up."""
    import errno

    p = tmp_path / "fifo"
    os.mkfifo(p)
    real = Driver.openat

    async def openat(self, path, flags, mode=0o666, *, blocking=False):
        if blocking:
            raise OSError(errno.EMFILE, os.strerror(errno.EMFILE), os.fsdecode(path))
        return await real(self, path, flags, mode)

    monkeypatch.setattr(Driver, "openat", openat)
    async with await open_file(tmp_path / "warmup", "w"):
        pass
    before = count_fds()  # (collects garbage first: rings of finished loops)
    with pytest.raises(OSError) as info:
        await open_file(p, "rb")
    assert info.value.errno == errno.EMFILE
    assert type(info.value) is OSError  # not wrapped in an exception group
    assert count_fds() == before
