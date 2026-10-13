"""wrap_file() and Path."""

from __future__ import annotations

import io
import os
import pathlib
import sys
import tempfile

import anyio
import pytest

import uringfile
from uringfile import AsyncFile, wrap_file

pytestmark = pytest.mark.anyio


# -- wrap_file ---------------------------------------------------------------


async def test_wrap_binary_continues_where_the_file_was(path):
    pathlib.Path(path).write_bytes(b"0123456789" * 1000)
    sync = open(path, "rb")
    assert sync.read(3) == b"012"  # ...and has read far ahead of that
    assert os.lseek(sync.fileno(), 0, os.SEEK_CUR) > 3
    f = wrap_file(sync)
    assert isinstance(f, AsyncFile)
    assert f.wrapped is sync
    assert f.name == path and f.mode == "rb"
    assert await f.tell() == 3
    assert await f.read(4) == b"3456"
    assert len(await f.read()) == 10_000 - 7
    await f.aclose()
    assert sync.closed and f.closed


async def test_wrap_text_mid_stream(path):
    text = "naïve\r\ncafé\r\n" * 500
    pathlib.Path(path).write_bytes(text.encode("utf-8"))
    with open(path, encoding="utf-8") as ref, open(path, encoding="utf-8") as sync:
        for n in (0, 1, 5, 6, 7, 200):
            ref.seek(0)
            sync.seek(0)
            assert sync.read(n) == ref.read(n)
            f = wrap_file(sync)
            assert f.encoding == "utf-8"
            assert await f.readline() == ref.readline()
            assert await f.tell() == ref.tell()
            assert await f.read(50) == ref.read(50)
            # Hand it back: the wrapper is done with, not the file.
            f._raw.detach_fd()
        sync.seek(0)


async def test_wrap_text_other_newline_mode(path):
    pathlib.Path(path).write_bytes(b"a\r\nb\rc\n")
    sync = open(path, newline="")
    async with wrap_file(sync, newline="") as f:
        assert await f.readlines() == ["a\r\n", "b\r", "c\n"]
    assert sync.closed


async def test_wrap_flushes_pending_writes_first(path):
    sync = open(path, "w+", encoding="utf-16")
    sync.write("already ")
    async with wrap_file(sync) as f:
        assert f.mode == "w+"
        await f.write("there")  # no second BOM
        await f.seek(0)
        assert await f.read() == "already there"
    assert pathlib.Path(path).read_bytes().decode("utf-16") == "already there"


async def test_wrap_append_and_unbuffered(path):
    pathlib.Path(path).write_bytes(b"abc")
    async with wrap_file(open(path, "ab")) as f:
        assert f.mode == "ab"
        assert await f.tell() == 3
        await f.write(b"def")
    async with wrap_file(open(path, "rb", buffering=0)) as f:
        assert isinstance(f.wrapped, io.FileIO)
        with pytest.raises(io.UnsupportedOperation):
            await f.peek()
        assert await f.read() == b"abcdef"


async def test_wrap_temporary_files():
    with tempfile.TemporaryFile() as tmp:
        tmp.write(b"spooled")
        f = wrap_file(tmp)
        await f.write(b" out")
        await f.seek(0)
        assert await f.read() == b"spooled out"
        await f.aclose()
        assert tmp.closed

    named = tempfile.NamedTemporaryFile("w+", suffix=".txt")
    name = named.name
    async with wrap_file(named) as f:
        await f.write("x\n")
        await f.flush()
        assert pathlib.Path(name).read_text() == "x\n"
    assert not os.path.exists(name)  # its own close() ran, deleting it


async def test_wrap_pipe(fifo):
    r, w = fifo
    async with wrap_file(os.fdopen(r, "rb")) as reader, wrap_file(os.fdopen(w, "wb")) as writer:
        await writer.write(b"through a pipe")
        await writer.aclose()
        assert await reader.read() == b"through a pipe"


@pytest.mark.parametrize("obj", [io.BytesIO(b"x"), io.StringIO("x"), object()])
async def test_wrap_needs_a_real_descriptor(obj):
    with pytest.raises(TypeError, match="no file descriptor"):
        wrap_file(obj)  # type: ignore[arg-type]


async def test_wrapped_is_only_for_wrapped_files(path):
    async with await uringfile.open_file(path, "w") as f:
        with pytest.raises(AttributeError):
            f.wrapped
        assert not hasattr(f, "wrapped")


async def test_unclosed_wrapper_warns_but_leaves_the_file(path):
    import gc

    sync = open(path, "w")
    f = wrap_file(sync)
    await f.write("flushed by the finalizer")
    with pytest.warns(ResourceWarning):
        del f
        gc.collect()
    assert not sync.closed
    sync.close()
    assert pathlib.Path(path).read_text() == "flushed by the finalizer"


# -- Path ------------------------------------------------------------------


async def test_path_reads_and_writes(tmp_path):
    p = uringfile.Path(tmp_path) / "sub" / "file.txt"
    assert type(p) is uringfile.Path
    assert isinstance(p, anyio.Path)
    await p.parent.mkdir()
    assert await p.write_text("héllo\n", encoding="utf-8") == 6
    assert await p.read_text(encoding="utf-8") == "héllo\n"
    assert await p.read_bytes() == "héllo\n".encode()
    assert await p.write_bytes(b"\x00\x01") == 2
    assert await p.write_bytes(memoryview(b"\x00\x01\x02")) == 3
    assert await p.read_bytes() == b"\x00\x01\x02"
    with pytest.raises(TypeError):
        await p.write_bytes("text")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        await p.write_text(b"bytes")  # type: ignore[arg-type]
    with pytest.raises(FileNotFoundError):
        await (p.parent / "missing").read_bytes()
    with pytest.raises(IsADirectoryError):
        await p.parent.read_text()


async def test_path_text_arguments(tmp_path):
    p = uringfile.Path(tmp_path, "f")
    await p.write_text("a\nb\n", newline="\r\n")
    assert await p.read_bytes() == b"a\r\nb\r\n"
    assert await p.read_text() == "a\nb\n"
    if sys.version_info >= (3, 13):
        assert await p.read_text(newline="") == "a\r\nb\r\n"
    await p.write_bytes(b"\xff")
    assert await p.read_text(encoding="utf-8", errors="replace") == "�"


async def test_path_open(tmp_path):
    p = uringfile.Path(tmp_path, "f")
    async with await p.open("w", encoding="latin-1", newline="\n") as f:
        assert isinstance(f, AsyncFile)
        assert f.encoding == "latin-1"
        await f.write("é\n")
    async with await p.open("rb", buffering=0) as f:
        assert await f.read() == b"\xe9\n"


async def test_path_derived_paths_keep_the_type(tmp_path):
    p = uringfile.Path(tmp_path, "a.txt")
    await p.write_text("x")
    for derived in (p.parent, p.with_name("b"), p.with_suffix(".md"), p.parent / "c",
                    p.parent.joinpath("d"), await p.resolve(), await p.absolute()):  # fmt: skip
        assert type(derived) is uringfile.Path
    children = [child async for child in p.parent.iterdir()]
    assert [type(c) for c in children] == [uringfile.Path]
    assert await children[0].read_text() == "x"


async def test_path_inherits_everything_else(tmp_path):
    p = uringfile.Path(tmp_path, "f")
    assert not await p.exists()
    await p.touch()
    assert await p.is_file()
    assert (await p.stat()).st_size == 0
    await p.rename(tmp_path / "g")
    assert os.fspath(p) == str(tmp_path / "f")
    await uringfile.Path(tmp_path, "g").unlink()
    assert os.listdir(tmp_path) == []
