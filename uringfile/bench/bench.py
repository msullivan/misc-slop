"""Compare uringfile with anyio's thread-backed files and the builtin open().

    python bench/bench.py [asyncio|trio|uvloop ...]

Each workload is run with uringfile, with anyio (the same API, each call a
hop to a worker thread), and with plain blocking calls (which stall the event
loop, but show what the work itself costs). Best of three.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time

import anyio

import uringfile

SMALL_FILES = 500
SMALL_SIZE = 4096
BIG_SIZE = 64 * 1024 * 1024
CHUNK = 64 * 1024
LINES = 100_000
WRITES = 100_000
COLD_FILES = 16
COLD_SIZE = 8 * 1024 * 1024


def drop_caches() -> bool:
    try:
        os.sync()
        with open("/proc/sys/vm/drop_caches", "w") as f:
            f.write("3")
        return True
    except OSError:
        return False


async def best(fn, repeat=3, setup=None):
    times = []
    for _ in range(repeat):
        if setup is not None:
            setup()
        start = time.perf_counter()
        await fn()
        times.append(time.perf_counter() - start)
    return min(times)


async def main(tmp: str) -> None:
    small = [os.path.join(tmp, f"small{i}") for i in range(SMALL_FILES)]
    for p in small:
        with open(p, "wb") as f:
            f.write(os.urandom(SMALL_SIZE))
    big = os.path.join(tmp, "big")
    with open(big, "wb") as f:
        f.write(os.urandom(BIG_SIZE))
    text = os.path.join(tmp, "text")
    with open(text, "w") as f:
        f.writelines(f"line number {i} of the text file\n" for i in range(LINES))
    out = os.path.join(tmp, "out")
    cold = [os.path.join(tmp, f"cold{i}") for i in range(COLD_FILES)]
    for p in cold:
        with open(p, "wb") as f:
            f.write(os.urandom(COLD_SIZE))
    record = b"x" * 49 + b"\n"

    def workloads(open_file):
        """The same five workloads for any anyio-style ``open_file``."""

        async def small_files():
            for p in small:
                async with await open_file(p, "rb") as f:
                    await f.read()

        async def big_read():
            async with await open_file(big, "rb") as f:
                while await f.read(CHUNK):
                    pass

        async def lines():
            n = 0
            async with await open_file(text) as f:
                async for _ in f:
                    n += 1
            assert n == LINES

        async def writes():
            async with await open_file(out, "wb") as f:
                for _ in range(WRITES):
                    await f.write(record)

        async def cold_concurrent():
            async def one(p):
                async with await open_file(p, "rb") as f:
                    while await f.read(CHUNK):
                        pass

            async with anyio.create_task_group() as tg:
                for p in cold:
                    tg.start_soon(one, p)

        return small_files, big_read, lines, writes, cold_concurrent

    async def blocking_open(*args, **kwargs):
        """The builtin, dressed up in the same interface."""
        fp = open(*args, **kwargs)

        class Sync:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                fp.close()

            def __aiter__(self):
                return self

            async def __anext__(self):
                line = fp.readline()
                if not line:
                    raise StopAsyncIteration
                return line

            async def read(self, n=-1):
                return fp.read(n)

            async def write(self, b):
                return fp.write(b)

        return Sync()

    names = [
        (f"open+read+close, {SMALL_FILES} x {SMALL_SIZE >> 10} KiB (cached)", SMALL_FILES, "file"),
        (f"read {BIG_SIZE >> 20} MiB in {CHUNK >> 10} KiB chunks (cached)", BIG_SIZE // CHUNK, "read"),
        (f"iterate {LINES} lines of text (cached)", LINES, "line"),
        (f"{WRITES} buffered writes of {len(record)} bytes", WRITES, "write"),
        (f"{COLD_FILES} x {COLD_SIZE >> 20} MiB concurrently (cold cache)", COLD_FILES * COLD_SIZE // CHUNK, "read"),
    ]  # fmt: skip
    impls = [
        ("uringfile", workloads(uringfile.open_file)),
        ("anyio (threads)", workloads(anyio.open_file)),
        ("blocking calls", workloads(blocking_open)),
    ]
    can_drop = drop_caches()
    for i, (title, count, unit) in enumerate(names):
        is_cold = "cold" in title
        if is_cold and not can_drop:
            print(f"\n{title}: skipped (cannot drop the page cache)")
            continue
        print(f"\n{title}")
        results = []
        for label, fns in impls:
            t = await best(fns[i], setup=drop_caches if is_cold else None)
            results.append((label, t))
        base = dict(results)["anyio (threads)"]
        for label, t in results:
            print(
                f"  {label:16} {t * 1e3:9.1f} ms  {t / count * 1e6:8.2f} us/{unit}"
                f"  {base / t:6.1f}x anyio"
            )


if __name__ == "__main__":
    backends = sys.argv[1:] or ["asyncio", "uvloop", "trio"]
    with tempfile.TemporaryDirectory(dir=os.environ.get("BENCH_DIR")) as tmp:
        for backend in backends:
            options = {"use_uvloop": True} if backend == "uvloop" else {}
            name = "asyncio" if backend == "uvloop" else backend
            print(f"\n===== {backend} =====", end="")
            anyio.run(main, tmp, backend=name, backend_options=options)
