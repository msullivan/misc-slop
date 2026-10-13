"""The public file API, case by case."""

from __future__ import annotations

import array
import errno
import fcntl
import gc
import io
import os
import pathlib
import threading
import warnings

import anyio
import pytest

import uringfile
from uringfile import AsyncFile, open_file

pytestmark = pytest.mark.anyio


# -- opening ----------------------------------------------------------------


async def test_context_manager_closes(path):
    async with await open_file(path, "wb") as f:
        assert isinstance(f, AsyncFile)
        assert not f.closed
        fd = f.fileno()
        await f.write(b"x")
    assert f.closed
    with pytest.raises(OSError):
        os.fstat(fd)
    await f.aclose()  # idempotent
    assert pathlib.Path(path).read_bytes() == b"x"


@pytest.mark.parametrize(
    "call",
    [
        lambda f: f.read(),
        lambda f: f.read(1),
        lambda f: f.readline(),
        lambda f: f.readlines(),
        lambda f: f.write(b"x"),
        lambda f: f.flush(),
        lambda f: f.seek(0),
        lambda f: f.tell(),
        lambda f: f.truncate(),
        lambda f: f.fsync(),
        lambda f: f.readinto(bytearray(1)),
        lambda f: f.peek(),
        lambda f: f.read1(),
    ],
)
@pytest.mark.parametrize("buffering", [0, -1])
async def test_closed_file_refuses_everything(path, call, buffering):
    f = await open_file(path, "w+b", buffering=buffering)
    await f.aclose()
    if buffering == 0 and call.__code__.co_names[-1] in ("peek", "read1"):
        with pytest.raises((ValueError, io.UnsupportedOperation)):
            await call(f)
        return
    with pytest.raises(ValueError, match="closed file"):
        await call(f)
    for sync in (f.fileno, f.isatty, f.readable, f.writable, f.seekable):
        with pytest.raises(ValueError, match="closed file"):
            sync()


async def test_closed_text_file(path):
    f = await open_file(path, "w+")
    await f.aclose()
    for call in (f.read, f.readline, f.tell, f.flush, lambda: f.write("x"), lambda: f.seek(0)):
        with pytest.raises(ValueError, match="closed file"):
            await call()


@pytest.mark.parametrize(
    "mode, buffering, kwargs",
    [
        ("rb", -1, {}), ("rb", 0, {}), ("wb", -1, {}), ("wb", 0, {}), ("ab", -1, {}),
        ("r+b", -1, {}), ("w+b", 0, {}), ("a+b", -1, {}), ("r", -1, {}), ("w", -1, {}),
        ("a+", -1, {}), ("rt", -1, {"encoding": "latin-1", "errors": "replace"}),
        ("w", 1, {}),
    ],
)  # fmt: skip
async def test_attributes_match_builtin(tmp_path, mode, buffering, kwargs):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    with open(a, mode, buffering=buffering, **kwargs) as ref:
        async with await open_file(b, mode, buffering=buffering, **kwargs) as f:
            assert f.mode == ref.mode
            assert f.name == b
            assert f.readable() == ref.readable()
            assert f.writable() == ref.writable()
            assert f.seekable() == ref.seekable()
            assert f.isatty() == ref.isatty()
            assert f.closed == ref.closed
            if "b" in mode:
                for attr in ("encoding", "errors", "newlines", "line_buffering"):
                    with pytest.raises(AttributeError):
                        getattr(f, attr)
            else:
                assert f.encoding == ref.encoding
                assert f.errors == ref.errors
                assert f.line_buffering == ref.line_buffering
            assert mode in repr(f) or f.mode in repr(f)
    assert "closed" in repr(f)


async def test_default_buffer_size_matches_builtin(path):
    pathlib.Path(path).write_bytes(b"")
    with open(path, "rb") as ref:
        async with await open_file(path, "rb") as f:
            # peek() on a big file returns one buffer's worth in both.
            pathlib.Path(path).write_bytes(bytes(4 * 1024 * 1024))
            assert len(await f.peek()) == len(ref.peek())


@pytest.mark.parametrize(
    "args, kwargs, exc",
    [
        (("rw",), {}, ValueError),
        (("",), {}, ValueError),
        (("b",), {}, ValueError),
        (("rr",), {}, ValueError),
        (("rz",), {}, ValueError),
        (("rbt",), {}, ValueError),
        ((7,), {}, TypeError),
        (("rb",), {"encoding": "utf-8"}, ValueError),
        (("rb",), {"errors": "strict"}, ValueError),
        (("rb",), {"newline": "\n"}, ValueError),
        (("r", 0), {}, ValueError),
        (("r",), {"newline": "x"}, ValueError),
        (("r",), {"encoding": "no-such-codec"}, LookupError),
        (("r",), {"encoding": "base64"}, LookupError),  # not a text encoding
        (("r",), {"closefd": False}, ValueError),
    ],
)
async def test_bad_arguments_fail_like_builtin(path, args, kwargs, exc):
    pathlib.Path(path).write_bytes(b"")
    with pytest.raises(exc):
        open(path, *args, **kwargs).close()
    with pytest.raises(exc):
        await open_file(path, *args, **kwargs)


async def test_bad_encoding_does_not_create_the_file(path):
    with pytest.raises(LookupError):
        await open_file(path, "w", encoding="no-such-codec")
    assert not os.path.exists(path)


async def test_line_buffering_in_binary_mode_warns(path):
    with pytest.warns(RuntimeWarning, match="line buffering"):
        f = await open_file(path, "wb", buffering=1)
    await f.aclose()


@pytest.mark.parametrize("convert", [str, os.fsencode, pathlib.Path, anyio.Path, uringfile.Path])
async def test_path_types(path, convert):
    async with await open_file(convert(path), "w") as f:
        await f.write("hi")
    async with await open_file(convert(path)) as f:
        assert await f.read() == "hi"


async def test_non_utf8_filename(tmp_path):
    name = os.fsencode(tmp_path) + b"/caf\xe9"
    async with await open_file(name, "wb") as f:
        await f.write(b"x")
    assert os.path.exists(name)
    async with await open_file(os.fsdecode(name), "rb") as f:
        assert await f.read() == b"x"


async def test_errors(tmp_path):
    with pytest.raises(FileNotFoundError) as info:
        await open_file(tmp_path / "missing")
    assert info.value.errno == errno.ENOENT
    assert info.value.filename == str(tmp_path / "missing")

    with pytest.raises(IsADirectoryError) as info:
        await open_file(tmp_path)
    assert info.value.filename == tmp_path

    (tmp_path / "there").write_bytes(b"")
    with pytest.raises(FileExistsError):
        await open_file(tmp_path / "there", "x")
    with pytest.raises(NotADirectoryError):
        await open_file(tmp_path / "there" / "below")
    with pytest.raises(ValueError, match="null byte"):
        await open_file("a\0b")
    with pytest.raises(ValueError, match="negative"):
        await open_file(-1)
    with pytest.raises(OSError) as info:
        await open_file(10**6)
    assert info.value.errno == errno.EBADF
    with pytest.raises(TypeError):
        await open_file(1.5)  # type: ignore[arg-type]


@pytest.mark.skipif(os.geteuid() == 0, reason="root can open anything")
async def test_permission_denied(path):
    pathlib.Path(path).write_bytes(b"")
    os.chmod(path, 0)
    with pytest.raises(PermissionError):
        await open_file(path)


async def test_failed_open_leaks_nothing(tmp_path, count_fds):
    async with await open_file(tmp_path / "warmup", "w"):
        pass  # this loop's ring now exists
    before = count_fds()
    for _ in range(5):
        with pytest.raises(IsADirectoryError):
            await open_file(tmp_path)
        with pytest.raises(io.UnsupportedOperation):
            r, w = os.pipe()
            os.close(w)
            try:
                await open_file(r, "r+b", closefd=False)
            finally:
                os.close(r)
    assert count_fds() == before


async def test_descriptor_is_close_on_exec(path):
    async with await open_file(path, "wb") as f:
        assert fcntl.fcntl(f.fileno(), fcntl.F_GETFD) & fcntl.FD_CLOEXEC


async def test_created_with_umask_applied(path):
    old = os.umask(0o027)
    try:
        async with await open_file(path, "w"):
            pass
    finally:
        os.umask(old)
    assert os.stat(path).st_mode & 0o777 == 0o640


async def test_open_descriptor(path):
    pathlib.Path(path).write_bytes(b"hello")
    fd = os.open(path, os.O_RDONLY)
    async with await open_file(fd, "rb") as f:
        assert f.name == fd
        assert await f.read() == b"hello"
    with pytest.raises(OSError):
        os.fstat(fd)

    fd = os.open(path, os.O_RDONLY)
    try:
        async with await open_file(fd, "rb", closefd=False) as f:
            assert await f.read(2) == b"he"
        os.fstat(fd)  # still open
        # Unbuffered, the descriptor's own position is the file's position.
        os.lseek(fd, 1, os.SEEK_SET)
        async with await open_file(fd, "rb", buffering=0, closefd=False) as f:
            assert await f.tell() == 1
            assert await f.read(2) == b"el"
        assert os.read(fd, 10) == b"lo"
    finally:
        os.close(fd)


async def test_opener(path):
    calls = []

    def opener(name, flags):
        calls.append((name, flags, threading.current_thread() is threading.main_thread()))
        return os.open(name, flags | os.O_CREAT, 0o600)

    async with await open_file(path, "r+b", opener=opener) as f:
        await f.write(b"x")
    assert calls == [(path, os.O_RDWR | os.O_CLOEXEC, False)]
    assert os.stat(path).st_mode & 0o777 == 0o600

    with pytest.raises(ValueError, match="opener returned -1"):
        await open_file(path, opener=lambda *a: -1)
    with pytest.raises(TypeError):
        await open_file(path, opener=lambda *a: "fd")
    with pytest.raises(ZeroDivisionError):
        await open_file(path, opener=lambda *a: 1 / 0)


# -- reading and writing ----------------------------------------------------


async def test_iteration_and_lines(path):
    lines = [f"line {i}\n" for i in range(5000)] + ["no newline"]
    async with await open_file(path, "w") as f:
        await f.writelines(lines)
    async with await open_file(path) as f:
        assert [line async for line in f] == lines
        await f.seek(0)
        assert await f.readlines() == lines
    async with await open_file(path, "rb") as f:
        assert [line async for line in f] == [s.encode() for s in lines]


@pytest.mark.parametrize("buffering", [0, 4096, -1])
async def test_large_file_roundtrip(path, buffering):
    block = bytes(range(256)) * 4096  # 1 MiB
    async with await open_file(path, "wb", buffering=buffering) as f:
        for i in range(5):
            view = memoryview(block)
            done = 0
            while done < len(view):
                done += await f.write(view[done:])
            await f.write(bytes([i]))
        assert await f.tell() == 5 * (len(block) + 1)
    async with await open_file(path, "rb", buffering=buffering) as f:
        for i in range(5):
            buf = bytearray(len(block))
            got = 0
            while got < len(buf):
                n = await f.readinto(memoryview(buf)[got:])
                assert n
                got += n
            assert buf == block
            assert await f.read(1) == bytes([i])
        assert await f.read(1) == b""
        await f.seek(0)
        whole = await f.read()
        assert len(whole) == 5 * (len(block) + 1)


async def test_buffer_protocol_objects(path):
    ints = array.array("I", range(1000))
    async with await open_file(path, "wb") as f:
        assert await f.write(ints) == ints.itemsize * 1000
        assert await f.write(memoryview(ints)[10:20]) == ints.itemsize * 10
        assert await f.write(memoryview(b"read-only")) == 9
        assert await f.write(bytearray(b"!")) == 1
        with pytest.raises(TypeError):
            await f.write("str")  # type: ignore[arg-type]
    async with await open_file(path, "rb") as f:
        back = array.array("I", bytes(ints.itemsize * 1000))
        assert await f.readinto(back) == ints.itemsize * 1000
        assert back == ints
        part = array.array("I", bytes(ints.itemsize * 10))
        assert await f.readinto1(part) == ints.itemsize * 10
        assert part == ints[10:20]
        assert await f.read() == b"read-only!"
        with pytest.raises(TypeError):
            await f.readinto(b"immutable")  # type: ignore[arg-type]
    async with await open_file(path, "w") as f:
        with pytest.raises(TypeError):
            await f.write(b"bytes")  # type: ignore[arg-type]


async def test_text_file_has_no_binary_methods(path):
    async with await open_file(path, "w+") as f:
        for call in (f.peek, f.read1, lambda: f.readinto(bytearray(1)),
                     lambda: f.readinto1(bytearray(1))):  # fmt: skip
            with pytest.raises(io.UnsupportedOperation):
                await call()  # type: ignore[misc]


async def test_append_mode(path):
    pathlib.Path(path).write_bytes(b"abc")
    async with await open_file(path, "ab") as f:
        assert await f.tell() == 3
        await f.seek(0)
        await f.write(b"def")  # O_APPEND: lands at the end regardless
        await f.flush()
        assert await f.tell() == 6
    assert pathlib.Path(path).read_bytes() == b"abcdef"


async def test_utf16_append_writes_one_bom(path):
    async with await open_file(path, "w", encoding="utf-16") as f:
        await f.write("a")
    async with await open_file(path, "a", encoding="utf-16") as f:
        await f.write("b")
    assert pathlib.Path(path).read_bytes().decode("utf-16") == "ab"
    assert pathlib.Path(path).read_bytes().count(b"\xff\xfe") == 1


async def test_encoding_errors_argument(path):
    pathlib.Path(path).write_bytes(b"ok \xff\xfe bad")
    async with await open_file(path, encoding="utf-8") as f:
        with pytest.raises(UnicodeDecodeError):
            await f.read()
    async with await open_file(path, encoding="utf-8", errors="replace") as f:
        assert await f.read() == "ok �� bad"
    async with await open_file(path, "w", encoding="ascii", errors="xmlcharrefreplace") as f:
        await f.write("é")
    assert pathlib.Path(path).read_bytes() == b"&#233;"


async def test_multibyte_character_split_across_reads(path):
    # Buffer and chunk boundaries fall inside characters.
    text = "日本語" * 5000
    pathlib.Path(path).write_text(text, encoding="utf-8")
    async with await open_file(path, encoding="utf-8", buffering=7) as f:
        out = []
        while piece := await f.read(1001):
            out.append(piece)
        assert "".join(out) == text


async def test_write_newline_translation(tmp_path):
    for newline, expected in [(None, os.linesep), ("", "\n"), ("\n", "\n"),
                              ("\r", "\r"), ("\r\n", "\r\n")]:  # fmt: skip
        p = tmp_path / repr(newline)
        async with await open_file(p, "w", newline=newline) as f:
            assert await f.write("a\nb\n") == 4
        assert p.read_bytes() == f"a{expected}b{expected}".encode()


async def test_fsync(path):
    async with await open_file(path, "wb") as f:
        await f.write(b"durable")
        await f.fsync()
        assert pathlib.Path(path).read_bytes() == b"durable"  # fsync flushes first
        await f.write(b"!")
        await f.fsync(datasync=True)
    async with await open_file(path, "w") as f:
        await f.write("text")
        await f.fsync()
        assert pathlib.Path(path).read_text() == "text"
    async with await open_file(path, "rb", buffering=0) as f:
        await f.fsync()


async def test_seek_whence_none_means_start(path):
    pathlib.Path(path).write_bytes(b"abcdef")
    async with await open_file(path, "rb") as f:
        await f.read(3)
        assert await f.seek(1, None) == 1
        assert await f.read(1) == b"b"
        assert await f.seek(-1, os.SEEK_END) == 5
        assert await f.seek(-2, os.SEEK_CUR) == 3
        with pytest.raises(OSError):
            await f.seek(-1)
        assert await f.tell() == 3  # a failed seek moves nothing
        assert await f.read() == b"def"


async def test_truncate_bounds(path):
    async with await open_file(path, "w+b") as f:
        await f.write(b"abcdef")
        with pytest.raises(OSError):
            await f.truncate(-1)
        with pytest.raises(OverflowError):
            await f.truncate(2**64 + 3)
        assert await f.truncate(2) == 2
        assert await f.truncate(10) == 10
    assert pathlib.Path(path).read_bytes() == b"ab" + bytes(8)


async def test_truncate_without_ring_support(path, monkeypatch):
    # Kernels before 6.9 have no IORING_OP_FTRUNCATE; a thread stands in.
    from uringfile import _driver, _uring

    driver = _driver.current_driver()
    monkeypatch.setattr(driver, "supported", driver.supported - {_uring.OP_FTRUNCATE})
    async with await open_file(path, "w+b") as f:
        await f.write(b"abcdef")
        assert await f.truncate(3) == 3
    assert pathlib.Path(path).read_bytes() == b"abc"


# -- things that are not regular files --------------------------------------


async def test_pipe(fifo):
    r, w = fifo
    async with await open_file(r, "rb") as reader, await open_file(w, "wb") as writer:
        assert not reader.seekable() and not writer.seekable()
        with pytest.raises(OSError):
            await reader.tell()
        with pytest.raises(OSError):
            await reader.seek(0)
        await writer.write(b"one\ntwo\n")
        await writer.flush()
        assert await reader.readline() == b"one\n"
        assert await reader.read1() == b"two\n"
        await writer.write(b"rest")
        await writer.aclose()
        assert await reader.read() == b"rest"
        assert await reader.read() == b""


async def test_text_over_pipe(fifo):
    r, w = fifo
    async with await open_file(r, encoding="utf-8") as reader:
        with pytest.raises(io.UnsupportedOperation):
            await reader.tell()
        async with await open_file(w, "w", encoding="utf-8") as writer:
            await writer.write("héllo\nwörld")
        assert await reader.readline() == "héllo\n"
        assert await reader.read() == "wörld"


async def test_update_mode_needs_a_seekable_file(fifo):
    r, _ = fifo
    for mode in ("r+b", "r+"):
        with pytest.raises(io.UnsupportedOperation, match="not seekable"):
            await open_file(r, mode, closefd=False)
    # Unbuffered has nothing to rewind, so it is allowed, as for open().
    f = await open_file(r, "r+b", buffering=0, closefd=False)
    await f.aclose()


async def test_terminal_is_line_buffered():
    try:
        master, slave = os.openpty()
    except OSError:
        pytest.skip("no pseudo-terminals here")
    try:
        async with await open_file(slave, "w", closefd=False) as f:
            assert f.isatty()
            assert f.line_buffering
            await f.write("partial")
            os.set_blocking(master, False)
            with pytest.raises(BlockingIOError):
                os.read(master, 100)
            await f.write(" line\n")
            assert os.read(master, 100) == b"partial line\r\n"
        async with await open_file(slave, "wb", closefd=False) as f:
            assert f.isatty()
    finally:
        os.close(master)
        os.close(slave)


async def test_dev_null_and_zero():
    async with await open_file("/dev/null", "wb") as f:
        assert await f.write(b"x" * 100_000) == 100_000
    async with await open_file("/dev/null", "rb") as f:
        assert await f.read() == b""
    async with await open_file("/dev/zero", "rb") as f:
        assert await f.read(100_000) == bytes(100_000)


# -- sharing a file between tasks -------------------------------------------


async def test_concurrent_writers_do_not_interleave(path):
    async def writer(f, tag):
        for i in range(200):
            await f.write(tag * 50 + b"\n")
            if i % 7 == 0:
                await f.flush()

    async with await open_file(path, "wb", buffering=64) as f:
        async with anyio.create_task_group() as tg:
            for tag in (b"a", b"b", b"c", b"d"):
                tg.start_soon(writer, f, tag)
    lines = pathlib.Path(path).read_bytes().splitlines()
    assert len(lines) == 800
    assert all(len(set(line)) == 1 and len(line) == 50 for line in lines)


async def test_concurrent_readers_each_get_whole_records(fifo):
    r, w = fifo
    got = []

    async def reader(f):
        while line := await f.readline():
            got.append(line)

    async with await open_file(r, "rb") as f, await open_file(w, "wb") as out:
        async with anyio.create_task_group() as tg:
            for _ in range(5):
                tg.start_soon(reader, f)
            for i in range(300):
                await out.write(b"%04d\n" % i)
                await out.flush()
            await out.aclose()
    assert sorted(got) == [b"%04d\n" % i for i in range(300)]


async def test_many_files_at_once(tmp_path):
    async def roundtrip(i):
        p = tmp_path / f"f{i}"
        data = bytes([i % 256]) * (i * 37 + 1)
        async with await open_file(p, "wb") as f:
            await f.write(data)
            await f.fsync()
        async with await open_file(p, "rb") as f:
            assert await f.read() == data

    async with anyio.create_task_group() as tg:
        for i in range(300):
            tg.start_soon(roundtrip, i)


# -- lifetime ---------------------------------------------------------------


async def test_unclosed_file_warns_and_still_flushes(path):
    f = await open_file(path, "w")
    await f.write("not lost")
    fd = f.fileno()
    with pytest.warns(ResourceWarning, match="unclosed file"):
        del f
        gc.collect()
    with pytest.raises(OSError):
        os.fstat(fd)
    assert pathlib.Path(path).read_text() == "not lost"


async def test_unowned_descriptor_is_left_alone_without_warning(path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT)
    try:
        f = await open_file(fd, "wb", closefd=False)
        await f.write(b"x")
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            del f
            gc.collect()
        os.fstat(fd)
        assert pathlib.Path(path).read_bytes() == b"x"
    finally:
        os.close(fd)


def test_file_outlives_its_event_loop(path, anyio_backend):
    """A file is just a descriptor; any loop's ring can drive it."""
    name, options = anyio_backend
    kwargs = dict(backend=name, backend_options=options)

    async def first():
        f = await open_file(path, "w+")
        await f.write("from the first loop\n")
        return f

    async def second(f):
        await f.write("from the second\n")
        await f.seek(0)
        lines = await f.readlines()
        await f.aclose()
        return lines

    f = anyio.run(first, **kwargs)
    assert anyio.run(second, f, **kwargs) == ["from the first loop\n", "from the second\n"]


def test_event_loops_in_several_threads(tmp_path, anyio_backend):
    name, options = anyio_backend
    errors = []

    async def work(i):
        p = tmp_path / f"t{i}"
        for _ in range(50):
            async with await open_file(p, "wb") as f:
                await f.write(bytes([i]) * 10_000)
                await f.fsync()
            async with await open_file(p, "rb") as f:
                assert await f.read() == bytes([i]) * 10_000

    def thread(i):
        try:
            anyio.run(work, i, backend=name, backend_options=options)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=thread, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors


def test_available():
    assert uringfile.available() is True
