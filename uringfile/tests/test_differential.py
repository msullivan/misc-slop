"""Differential tests: random operation sequences against the builtin open().

Two copies of the same file are opened the same way, one with ``open`` and
one with ``uringfile.open_file``. The same operations are applied to both
and every result, every exception type, every ``tell()`` and the final file
contents must agree.
"""

from __future__ import annotations

import io
import os
import random
import shutil
import sys

import pytest

from uringfile import open_file

pytestmark = pytest.mark.anyio

SEEDS = range(12)


def outcome(fn, *args):
    try:
        return ("ok", fn(*args))
    except Exception as exc:
        return ("raised", type(exc))


async def aoutcome(fn, *args):
    try:
        return ("ok", await fn(*args))
    except Exception as exc:
        return ("raised", type(exc))


class Pair:
    """The reference file and ours, driven in lockstep."""

    def __init__(self, ref, ours, log):
        self.ref, self.ours, self.log = ref, ours, log

    async def same(self, name, *args):
        """Apply ``name(*args)`` to both; results must be identical."""
        expected = outcome(getattr(self.ref, name), *args)
        actual = await aoutcome(getattr(self.ours, name), *args)
        self.log.append((name, args, expected))
        if actual != expected:
            pytest.fail(self.explain(actual), pytrace=False)
        return expected

    def explain(self, actual):
        def short(x):
            text = repr(x)
            return text if len(text) <= 100 else f"{text[:100]}... ({len(text)} chars)"

        lines = [f"{name}{short(args)} -> {short(res)}" for name, args, res in self.log[-25:]]
        return "ours gave %s after:\n  %s" % (short(actual), "\n  ".join(lines))

    async def partial(self, name, arg):
        """For read1-style calls, whose length legitimately depends on what
        happens to be buffered: whatever we return must be what comes next."""
        got = await getattr(self.ours, name)(arg)
        expected = self.ref.read(len(got)) if got else self.ref.read(1 if arg else 0)
        self.log.append((name, (arg,), ("ok", expected)))
        assert got == expected, self.explain(got)
        if arg:
            assert got or not expected

    async def partial_into(self, name, size):
        buf = bytearray(size)
        n = await getattr(self.ours, name)(buf)
        expected = self.ref.read(n) if n else self.ref.read(1 if size else 0)
        self.log.append((name, (size,), ("ok", expected)))
        assert bytes(buf[:n]) == expected, self.explain(bytes(buf[:n]))

    async def peek(self):
        got = await self.ours.peek()
        pos = self.ref.tell()
        expected = self.ref.read(len(got)) if got else self.ref.read(1)
        self.ref.seek(pos)
        self.log.append(("peek", (), ("ok", expected)))
        assert got == expected, self.explain(got)
        assert (await self.ours.tell()) == pos


def make_pair_paths(tmp_path, content: bytes | None):
    a, b = tmp_path / "ref", tmp_path / "ours"
    if content is not None:
        a.write_bytes(content)
        shutil.copy(a, b)
    return a, b


def random_bytes(rng, n):
    alphabet = b"abcdefghij\n\n\r \x00\xff"
    return bytes(rng.choice(alphabet) for _ in range(n))


# ---------------------------------------------------------------------------
# binary
# ---------------------------------------------------------------------------

BINARY_MODES = ["rb", "r+b", "wb", "w+b", "ab", "a+b"]
BUFFERINGS = [0, 2, 7, 64, 8192]


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("buffering", BUFFERINGS)
@pytest.mark.parametrize("mode", BINARY_MODES)
async def test_binary(tmp_path, mode, buffering, seed):
    rng = random.Random(f"{mode}/{buffering}/{seed}")
    size = rng.choice([0, 1, 5, 50, 300, 20_000])
    a, b = make_pair_paths(tmp_path, random_bytes(rng, size))
    ref = open(a, mode, buffering=buffering)
    ours = await open_file(b, mode, buffering=buffering)
    pair = Pair(ref, ours, [])
    assert ours.mode == ref.mode
    assert (ours.readable(), ours.writable(), ours.seekable()) == (
        ref.readable(), ref.writable(), ref.seekable(),
    )  # fmt: skip
    small = lambda: rng.choice([0, 1, 2, 3, 6, 7, 8, 13, 63, 64, 65, 100, 1000])
    readahead = False  # might the reference be holding read-ahead?
    try:
        for _ in range(60):
            op = rng.choice(
                ["read", "read", "readall", "readline", "readline_n", "readinto", "write",
                 "write", "bigwrite", "seek_set", "seek_cur", "seek_end", "tell", "truncate",
                 "flush", "read1", "readinto1", "peek", "readlines"]
            )  # fmt: skip
            if mode == "a+b" and op in ("write", "bigwrite") and readahead:
                # Appending while read-ahead is buffered: the C io module
                # keeps serving the old read-ahead as if the write had gone
                # where the reader was, and ends up reporting a position
                # past the end of the file. The pure-Python _pyio does not,
                # and neither do we. Make it drop its buffer first.
                await pair.same("seek", 0, os.SEEK_END)
                readahead = False
            if op.startswith(("read", "peek")):
                readahead = True
            elif op == "seek_end":
                readahead = False
            if op.startswith(("read", "peek")) and not ref.readable():
                # The builtins are not consistent about which argument
                # checks come before noticing the file cannot be read
                # (read(None) is a TypeError, readline(0) succeeds). We
                # always refuse, and don't compare.
                with pytest.raises(io.UnsupportedOperation):
                    await ours.read(small())
                with pytest.raises(io.UnsupportedOperation):
                    await ours.readline(small())
            elif op == "read":
                await pair.same("read", small())
            elif op == "readall":
                await pair.same("read", rng.choice([-1, None]))
            elif op == "readline":
                await pair.same("readline")
            elif op == "readline_n":
                await pair.same("readline", small())
            elif op == "readlines":
                await pair.same("readlines", rng.choice([-1, 1, 20]))
            elif op == "readinto":
                n = small()
                x, y = bytearray(n), bytearray(n)
                expected = outcome(ref.readinto, x)
                actual = await aoutcome(ours.readinto, y)
                pair.log.append(("readinto", (n,), expected))
                assert actual == expected and x == y, pair.explain((actual, y))
            elif op == "write":
                await pair.same("write", random_bytes(rng, small()))
            elif op == "bigwrite":
                data = random_bytes(rng, rng.choice([8192, 10_000]))
                await pair.same("write", rng.choice([bytes, bytearray, memoryview])(data))
            elif op == "seek_set":
                await pair.same("seek", rng.choice([0, 1, small(), size, size + 10, -1]))
            elif op == "seek_cur":
                await pair.same("seek", rng.choice([0, 1, -1, small(), -small()]), os.SEEK_CUR)
            elif op == "seek_end":
                await pair.same("seek", rng.choice([0, -1, -small(), 5]), os.SEEK_END)
            elif op == "tell":
                await pair.same("tell")
            elif op == "truncate":
                await pair.same("truncate", rng.choice([None, 0, small(), size]))
            elif op == "flush":
                await pair.same("flush")
            elif buffering:
                if op == "read1":
                    await pair.partial("read1", rng.choice([-1, small()]))
                elif op == "readinto1":
                    await pair.partial_into("readinto1", small())
                elif op == "peek":
                    await pair.peek()
            if rng.random() < 0.3:
                await pair.same("tell")
    finally:
        ref.close()
        await ours.aclose()
    assert b.read_bytes() == a.read_bytes()


@pytest.mark.parametrize("mode", ["xb", "x+b"])
async def test_exclusive_create(tmp_path, mode):
    a, b = make_pair_paths(tmp_path, None)
    with open(a, mode) as ref:
        async with await open_file(b, mode) as ours:
            assert ours.mode == ref.mode
            pair = Pair(ref, ours, [])
            await pair.same("write", b"abc")
            await pair.same("tell")
    assert b.read_bytes() == a.read_bytes()
    with pytest.raises(FileExistsError):
        await open_file(b, mode)


# ---------------------------------------------------------------------------
# text
# ---------------------------------------------------------------------------

TEXT_MODES = ["r", "r+", "w", "w+", "a", "a+"]
ENCODINGS = ["utf-8", "utf-8-sig", "utf-16", "utf-32-le", "latin-1", "shift_jis"]
NEWLINES = [None, "", "\n", "\r", "\r\n"]


def random_text(rng, n, encoding):
    alphabet = "abcdefg  \n\n\r\n\r"
    if encoding != "latin-1":
        alphabet += "日本語"
    if encoding.startswith("utf"):
        alphabet += "é€\U0001f600"
    elif encoding == "latin-1":
        alphabet += "éÿ"
    return "".join(rng.choice(alphabet) for _ in range(n))


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("newline", NEWLINES, ids=repr)
@pytest.mark.parametrize("encoding", ENCODINGS)
@pytest.mark.parametrize("mode", TEXT_MODES)
async def test_text(tmp_path, mode, encoding, newline, seed):
    rng = random.Random(f"{mode}/{encoding}/{newline!r}/{seed}")
    size = rng.choice([0, 1, 40, 400, 30_000])
    initial = random_text(rng, size, encoding).encode(encoding)
    a, b = make_pair_paths(tmp_path, initial)
    buffering = rng.choice([-1, 16, 100])
    kwargs = dict(buffering=buffering, encoding=encoding, newline=newline)
    ref = open(a, mode, **kwargs)
    ours = await open_file(b, mode, **kwargs)
    pair = Pair(ref, ours, [])
    assert (ours.encoding, ours.errors, ours.mode) == (ref.encoding, ref.errors, ref.mode)
    small = lambda: rng.choice([0, 1, 2, 3, 7, 50, 500, 9000])

    async def tell():
        """tell() on both; returns the cookie, or None if both raised.

        The two cookies must name the same position but need not be equal:
        where a position has several encodings, which one the builtin
        returns depends on its read-ahead (see Text.tell). When they differ,
        check that each file can resume from either, then carry on from
        ours. (Not from each file's own: after seeking to the builtin's
        fancier cookie, a write resets its decoder and with it the pending
        "\r" that the cookie was carrying, and a character goes missing.)
        """
        expected = outcome(ref.tell)
        actual = await aoutcome(ours.tell)
        pair.log.append(("tell", (), (expected, actual)))
        if actual[0] != expected[0] or (actual[0] == "raised" and actual != expected):
            pytest.fail(pair.explain(actual), pytrace=False)
        if actual[0] != "ok":
            return None
        theirs, mine = expected[1], actual[1]
        if theirs != mine:
            for a_cookie, b_cookie in ((theirs, mine), (mine, theirs), (mine, mine)):
                assert outcome(ref.seek, a_cookie) == ("ok", a_cookie)
                assert await aoutcome(ours.seek, b_cookie) == ("ok", b_cookie)
                if (a_cookie, b_cookie) != (mine, mine):
                    await pair.same("read", 40)
        cookies.append(mine)
        return mine

    cookies = [0]
    # The standard library leaves a write straight after a read, with no
    # seek in between, at the mercy of how much it happened to read ahead.
    # Like its documentation, keep them apart.
    just_read = False
    try:
        for _ in range(50):
            op = rng.choice(
                ["read", "read", "readall", "readline", "readline", "readline_n", "write",
                 "write", "seek_cookie", "seek_start", "seek_end", "seek_cur", "tell",
                 "truncate", "flush", "readlines", "bad_seek"]
            )  # fmt: skip
            if op == "write" and just_read:
                await pair.same("seek", await tell())
                just_read = False

            if op == "read":
                await pair.same("read", small())
            elif op == "readall":
                await pair.same("read")
            elif op == "readline":
                await pair.same("readline")
            elif op == "readline_n":
                await pair.same("readline", small())
            elif op == "readlines":
                await pair.same("readlines", rng.choice([-1, 30]))
                # The builtin refuses to tell() after being iterated over
                # part-way ("telling position disabled by next() call"),
                # until the next seek. We have no such restriction.
                op = "seek_cookie"
                await pair.same("seek", rng.choice(cookies))
            elif op == "write":
                await pair.same("write", random_text(rng, small(), encoding))
                if sys.version_info < (3, 11):
                    # Python 3.10's text files can lose a write that is
                    # followed by a read with no flush in between (the
                    # bytes never reach the file). tell() flushes.
                    await tell()
            elif op == "seek_cookie":
                # (A cookie from before the file was rewritten may now point
                # into the middle of a character; then both fail alike.)
                await pair.same("seek", rng.choice(cookies))
            elif op == "seek_start":
                await pair.same("seek", 0)
            elif op == "seek_end":
                await pair.same("seek", 0, os.SEEK_END)
            elif op == "seek_cur":
                cookie = await tell()  # seek(0, SEEK_CUR) is seek(tell())
                if cookie is not None:
                    await pair.same("seek", cookie)
            elif op == "bad_seek":
                await pair.same("seek", rng.choice([1, -1]), rng.choice([1, 2]))
            elif op == "tell":
                pass  # done below, often
            elif op == "truncate":
                # A text file's truncate() cuts wherever its buffer is,
                # read-ahead included. Put both buffers in the same place.
                cookie = await tell()
                if cookie is not None:
                    await pair.same("seek", cookie)
                    await pair.same("truncate")
                    just_read = False
            elif op == "flush":
                await pair.same("flush")
            if op.startswith("read"):
                just_read = True
            elif op.startswith("seek"):
                just_read = False
            last = pair.log[-1][2] if pair.log else None
            if (
                isinstance(last, tuple)
                and last[0] == "raised"
                and issubclass(last[1], UnicodeError)
            ):
                # E.g. a write into the middle of UTF-16 text resets the
                # decoder, which then wants a BOM. How much input a failed
                # read has eaten is nobody's contract; start over.
                await pair.same("seek", 0)
                just_read = False
            if rng.random() < 0.5:
                await tell()
    finally:
        ref.close()
        await ours.aclose()
    assert b.read_bytes() == a.read_bytes()


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-8-sig", "utf-7", "iso2022_jp"])
@pytest.mark.parametrize("newline", NEWLINES, ids=repr)
async def test_text_tell_at_every_position(tmp_path, encoding, newline):
    """After reading n characters, for every n: our cookie and the builtin's
    are interchangeable, and seeking to either resumes exactly there."""
    text = "aé\r\n日本語\rb\n\U0001f600\r\n\r\nz" * 3
    if encoding == "iso2022_jp":
        text = "ab\r\nあいう\rc\n漢字\r\n\r\nz" * 3
    a, b = make_pair_paths(tmp_path, text.encode(encoding))
    plain = 0
    with open(a, encoding=encoding, newline=newline) as ref:
        async with await open_file(b, encoding=encoding, newline=newline) as ours:
            whole = ref.read()
            for n in range(len(whole) + 1):
                ref.seek(0)
                await ours.seek(0)
                assert await ours.read(n) == ref.read(n)
                theirs, mine = ref.tell(), await ours.tell()
                plain += mine < 2**64
                # Never a fancier cookie than the builtin's.
                assert mine <= theirs, n
                for cookie in (theirs, mine):
                    for f in (ref, ours):
                        r = f.seek(0, os.SEEK_END)
                        if f is ours:
                            await r
                    ref.seek(cookie)
                    await ours.seek(cookie)
                    assert await ours.read(2) == ref.read(2) == whole[n : n + 2]
                    assert await ours.read() == ref.read() == whole[n + 2 :]
    if encoding == "utf-8" and newline:
        # Stateless codec and no "\r" being held back to see what follows
        # it: every position is a plain byte offset.
        assert plain == len(whole) + 1


@pytest.mark.parametrize("newline", NEWLINES, ids=repr)
async def test_newlines_attribute(tmp_path, newline):
    # (Not checked in the random test above: what has been *seen* depends on
    # read-ahead, and the C module's tell() makes it forget.)
    a, b = make_pair_paths(tmp_path, b"one\ntwo\r\nthree\rfour")
    with open(a, newline=newline) as ref:
        async with await open_file(b, newline=newline) as ours:
            assert ours.newlines == ref.newlines is None
            assert await ours.readline() == ref.readline()
            assert ours.newlines == ref.newlines
            assert await ours.read() == ref.read()
            assert ours.newlines == ref.newlines
    with pytest.raises(AttributeError):
        async with await open_file(b, "rb") as f:
            f.newlines


@pytest.mark.parametrize("newline", NEWLINES, ids=repr)
async def test_text_lines_longer_than_any_chunk(tmp_path, newline):
    rng = random.Random(1)
    lines = ["x" * rng.choice([0, 1, 8191, 8192, 8193, 70_000, 300_000]) for _ in range(12)]
    data = "\r\n".join(lines) + "\rlast\nend"
    a, b = make_pair_paths(tmp_path, data.encode())
    with open(a, newline=newline) as ref:
        async with await open_file(b, newline=newline) as ours:
            expected = ref.readlines()
            assert [line async for line in ours] == expected
            assert ours.newlines == ref.newlines
            assert await ours.tell() == ref.tell()


async def test_readall_of_a_growing_file(tmp_path):
    # The size seen at open() is only a hint.
    p = tmp_path / "f"
    p.write_bytes(b"a" * 1000)
    async with await open_file(p, "rb") as f:
        with open(p, "ab") as g:
            g.write(b"b" * 50_000)
        assert await f.read() == b"a" * 1000 + b"b" * 50_000


async def test_proc_files_report_no_size():
    async with await open_file("/proc/self/status", "rb") as f:
        data = await f.read()
    assert data.startswith(b"Name:") and len(data) > 100
    async with await open_file("/proc/self/status") as f:
        assert (await f.readline()).startswith("Name:")
