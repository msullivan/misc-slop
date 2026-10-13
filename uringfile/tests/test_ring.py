"""The synchronous ring bindings, without any event loop."""

from __future__ import annotations

import errno
import os
import select

import pytest

from uringfile import _uring as u


@pytest.fixture
def ring():
    r = u.Ring(4)
    yield r
    r.close()


def wait_for(ring, efd, n=1):
    out = []
    while len(out) < n:
        assert select.select([efd], [], [], 5)[0], "timed out waiting for a completion"
        os.eventfd_read(efd)
        out += ring.reap()
    return out


def test_geometry(ring):
    assert ring.sq_entries == 4
    assert ring.cq_entries >= ring.sq_entries
    assert ring.features & u.FEAT_NODROP
    assert ring.features & u.FEAT_RW_CUR_POS


def test_probe(ring):
    ops = ring.probe()
    assert {u.OP_NOP, u.OP_READ, u.OP_WRITE, u.OP_OPENAT, u.OP_CLOSE, u.OP_FSYNC} <= ops
    assert 250 not in ops


def test_nop_roundtrip_and_wraparound(ring):
    # Far more operations than slots: head and tail must wrap correctly.
    for i in range(1, 100):
        ring.push(u.OP_NOP, -1, 0, 0, 0, 0, i)
        assert ring.submit() == 1
        assert ring.reap() == [(i, 0)]
    assert ring.reap() == []


def test_batch(ring):
    for i in range(4):
        ring.push(u.OP_NOP, -1, 0, 0, 0, 0, 10 + i)
    with pytest.raises(BufferError):
        ring.push(u.OP_NOP, -1, 0, 0, 0, 0, 99)
    assert ring.pending == 4
    assert ring.submit() == 4
    assert [c[0] for c in ring.reap()] == [10, 11, 12, 13]


def test_unpush(ring):
    ring.push(u.OP_NOP, -1, 0, 0, 0, 0, 1)
    ring.push(u.OP_NOP, -1, 0, 0, 0, 0, 2)
    ring.unpush()
    assert ring.submit() == 1
    assert ring.reap() == [(1, 0)]


def test_error_is_negative_errno(ring):
    ring.push(u.OP_CLOSE, 10**6, 0, 0, 0, 0, 1)
    ring.submit()
    assert ring.reap() == [(1, -errno.EBADF)]


def test_unknown_opcode_completes_with_einval(ring):
    ring.push(250, -1, 0, 0, 0, 0, 1)
    ring.submit()
    assert ring.reap() == [(1, -errno.EINVAL)]


def test_eventfd_is_signalled(ring):
    efd = os.eventfd(0, os.EFD_NONBLOCK)
    try:
        ring.register_eventfd(efd)
        with pytest.raises(BlockingIOError):
            os.eventfd_read(efd)
        ring.push(u.OP_NOP, -1, 0, 0, 0, 0, 5)
        ring.submit()
        assert wait_for(ring, efd) == [(5, 0)]
    finally:
        os.close(efd)


def test_read_write_use_the_file_position(ring, tmp_path):
    # Whether these complete inside submit() or later on a kernel worker is
    # up to the filesystem, so always go through the eventfd.
    efd = os.eventfd(0, os.EFD_NONBLOCK)
    ring.register_eventfd(efd)
    fd = os.open(tmp_path / "f", os.O_RDWR | os.O_CREAT)
    try:
        for part in (b"hello ", bytearray(b"world"), memoryview(b"!")):
            addr, n, keep = u.readable_address(part)
            ring.push(u.OP_WRITE, fd, u.CUR_POS, addr, n, 0, 1)
            ring.submit()
            assert wait_for(ring, efd) == [(1, n)]
        assert os.lseek(fd, 0, os.SEEK_CUR) == 12
        os.lseek(fd, 6, os.SEEK_SET)
        buf = bytearray(16)
        addr, keep = u.writable_address(memoryview(buf))
        ring.push(u.OP_READ, fd, u.CUR_POS, addr, len(buf), 0, 2)
        ring.submit()
        assert wait_for(ring, efd) == [(2, 6)]
        assert buf[:6] == b"world!"
        assert os.lseek(fd, 0, os.SEEK_CUR) == 12
    finally:
        os.close(fd)
        os.close(efd)


def test_cq_overflow_is_recoverable():
    # 1 SQ entry means 2 CQ entries. Leave more than that uncollected.
    ring = u.Ring(1)
    try:
        assert ring.cq_entries == 2
        for i in range(1, 8):
            ring.push(u.OP_NOP, -1, 0, 0, 0, 0, i)
            ring.submit()
        assert ring.overflowed
        seen = []
        while len(seen) < 7:
            got = ring.reap()
            seen += [c[0] for c in got]
            if ring.overflowed:
                ring.flush_overflow()
            else:
                assert got
        assert seen == list(range(1, 8))
        assert not ring.overflowed
    finally:
        ring.close()


def test_writable_address_pins_the_buffer():
    buf = bytearray(8)
    _, keep = u.writable_address(memoryview(buf))
    with pytest.raises(BufferError):
        buf.extend(b"x")
    del keep
    buf.extend(b"x")


def test_readable_address_of_empty_and_readonly():
    assert u.readable_address(bytearray())[:2] == (0, 0)
    addr, n, keep = u.readable_address(memoryview(b"abc")[1:])
    assert n == 2 and addr


def test_close_is_idempotent():
    ring = u.Ring(2)
    fd = ring.fd
    ring.close()
    ring.close()
    assert ring.closed
    with pytest.raises(OSError):
        os.fstat(fd)


def test_worker_limit_is_per_thread_and_adjustable():
    import threading

    seen = []

    def body():
        # The first ring a thread creates sizes its worker pool...
        small = u.Ring(1)
        big = u.Ring(64)
        try:
            seen.append(big.set_max_workers(0))  # query
            seen.append(big.set_max_workers(17))  # returns the old limits
            seen.append(small.set_max_workers(0))  # ...which all its rings share
        finally:
            small.close()
            big.close()

    t = threading.Thread(target=body)
    t.start()
    t.join()
    (bounded, unbounded), previous, after = seen
    assert bounded == 1 and unbounded > 0
    assert previous == (bounded, unbounded)
    assert after == (17, unbounded)


def test_pending_tracks_what_the_kernel_has_taken(ring):
    assert ring.pending == 0
    ring.push(u.OP_NOP, -1, 0, 0, 0, 0, 1)
    ring.push(u.OP_NOP, -1, 0, 0, 0, 0, 2)
    assert ring.pending == 2
    ring.submit()
    assert ring.pending == 0
    ring.unpush()  # nothing left to take back: must not rewind past the kernel
    ring.push(u.OP_NOP, -1, 0, 0, 0, 0, 3)
    assert ring.submit() == 1
    assert [c[0] for c in ring.reap()] == [1, 2, 3]


def test_drain_can_be_interrupted_without_losing_a_completion(ring):
    for i in (1, 2, 3):
        ring.push(u.OP_NOP, -1, 0, 0, 0, 0, i)
    ring.submit()
    seen = []

    def handler(user_data, res):
        seen.append(user_data)
        if len(seen) == 2:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        ring.drain(handler)
    assert seen == [1, 2]
    assert [c[0] for c in ring.reap()] == [2, 3]  # 2 again, and nothing skipped


def test_stat_cached(tmp_path, monkeypatch):
    import stat

    (tmp_path / "f").write_bytes(b"x" * 12345)
    for target, check in ((tmp_path / "f", stat.S_ISREG), (tmp_path, stat.S_ISDIR)):
        fd = os.open(target, os.O_RDONLY)
        try:
            st = os.fstat(fd)
            assert u.stat_cached(fd) == (st.st_mode, st.st_size, st.st_blksize)
            assert check(u.stat_cached(fd)[0])
            # Without statx() in the C library, plain fstat() stands in.
            with monkeypatch.context() as m:
                m.setattr(u, "_statx", None)
                assert u.stat_cached(fd) == (st.st_mode, st.st_size, st.st_blksize)
        finally:
            os.close(fd)
    r, w = os.pipe()
    try:
        assert stat.S_ISFIFO(u.stat_cached(r)[0])
    finally:
        os.close(r)
        os.close(w)
    with pytest.raises(OSError) as info:
        u.stat_cached(10**6)
    assert info.value.errno == errno.EBADF
