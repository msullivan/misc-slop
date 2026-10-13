# uringfile

Asynchronous file I/O on io_uring with [anyio](https://anyio.readthedocs.io/)'s
file API. Pure Python (ctypes + mmap, no C extension), Linux only, runs on
asyncio, uvloop and Trio.

```python
import anyio
from uringfile import open_file, Path

async def main():
    async with await open_file("data.log") as f:      # same arguments as open()
        async for line in f:
            ...
    async with await open_file("out.bin", "wb") as f:
        await f.write(b"...")
        await f.fsync()
    text = await Path("notes.txt").read_text()

anyio.run(main)                    # or backend="trio"
```

`anyio.open_file` sends every call to a worker thread. Here the reads, writes,
opens and closes are io_uring operations submitted from the event loop thread,
and the loop finds out about completions through an eventfd.

## Requirements

- Linux 5.6 or later with io_uring permitted (it is off under Docker's default
  seccomp profile and wherever `kernel.io_uring_disabled` says so).
  `uringfile.available()` tells you; nothing falls back to threads on its own.
- Python 3.10+, anyio 4.14+.

Developed and tested on Linux 6.18 / x86-64 only. The code paths for older
kernels (no `IORING_SETUP_COOP_TASKRUN`, no `IORING_OP_FTRUNCATE`, no worker
limit) exist, and the ftruncate one is exercised by a test that hides the
opcode, but none has run on an old kernel.

## API

The same as anyio's, so it can be swapped in:

| | |
|---|---|
| `await open_file(file, mode="r", buffering=-1, encoding=None, errors=None, newline=None, closefd=True, opener=None)` | Arguments and meaning of the builtin `open()`. Returns an `AsyncFile`. |
| `wrap_file(fileobj, *, newline=None)` | Take over an already open file object that has a real descriptor. |
| `Path` | Subclass of `anyio.Path`; `open`, `read_bytes`, `read_text`, `write_bytes`, `write_text` use the ring, everything else is inherited (threads). |
| `available()` | Whether io_uring is usable in this process. |

`AsyncFile` has the methods of `anyio.AsyncFile` — `read`, `read1`, `readline`,
`readlines`, `readinto`, `readinto1`, `write`, `writelines`, `truncate`, `seek`,
`tell`, `flush`, `aclose`, async iteration over lines, `async with` — plus
`peek()` and `fsync(*, datasync=False)`. `name`, `mode`, `closed`, `encoding`,
`errors`, `newlines`, `line_buffering`, `fileno()`, `isatty()`, `readable()`,
`writable()`, `seekable()` are synchronous, as in anyio.

Differences from anyio that are visible:

- `AsyncFile.wrapped` exists only on files made by `wrap_file`. There is no
  underlying `io` object otherwise: buffering and text decoding are
  reimplemented (`_io.py`), since the C ones can only do blocking reads.
- `uringfile.AsyncFile` is not a subclass of `anyio.AsyncFile`, so
  `Path.open` is not a type-correct override (it is marked as such).
- `wrap_file` needs a real file descriptor. It cannot recover input the old
  object had already buffered from a pipe, or the `newline` it was opened
  with (hence the argument).

## How it works

`_uring.py` — the ring. `io_uring_setup/enter/register` through libc's
`syscall()`, the SQ/CQ rings and SQE array `mmap`ed and accessed with `struct`.
No SQPOLL, no registered buffers or files.

`_driver.py` — one ring and one eventfd per event loop, created on first use
and kept in an anyio `RunVar`. The eventfd is registered with
`IORING_REGISTER_EVENTFD`. To run an operation, a task writes the SQE, calls
`io_uring_enter` to submit, and then:

- if the completion is already in the CQ (cached data usually is), takes it
  and returns without touching the event loop;
- otherwise waits. There is no background task, because anyio has no portable
  way to start one outside a task group. Waiting tasks take turns instead: at
  most one sleeps until the eventfd is signalled and dispatches whatever
  completes; the rest wait on an `anyio.Event` each. When that task's own
  operation finishes, or it is cancelled, it hands the role to another.

Sleeping until the eventfd is signalled is the only contact with the event
loop, and the only code that differs between loops (`Driver._signalled`):

- Trio: `anyio.wait_readable(eventfd)`.
- asyncio and uvloop: the eventfd gets a reader (`loop.add_reader`) once, on
  the first wait, and keeps it. The callback reads the eventfd and resolves
  the future the waiting task is asleep on. `anyio.wait_readable` would add
  and remove the reader on every call, which is two `epoll_ctl` calls and
  about 15 µs per wait on asyncio.

  The price of a permanent reader: operations that complete on the spot
  signal the eventfd as well, so the next trip through the loop runs the
  callback for nothing (it has to read the eventfd, or the loop would never
  sleep again). That is 1–2 µs per loop iteration in which something
  completed inline.

`_io.py` — unbuffered, buffered and text layers with the behaviour of
`io.FileIO`, `io.BufferedRandom` and the C `io.TextIOWrapper`, including
`tell()` cookies in the C layout. `_file.py` — `AsyncFile`, `open_file`,
`wrap_file`.

Not ring operations: `seek`/`tell` (`lseek`, which does not block), `isatty`,
a `statx(AT_STATX_DONT_SYNC)` at open (io_uring's own statx always goes to a
kernel worker thread, which costs more than the rest of a small-file read),
a custom `opener`, the inherited `Path` methods, and `truncate` before
Linux 6.9.

### Checkpoints

A call served from the buffer returns immediately. A call that reaches the
kernel checks for cancellation first; if the kernel answers on the spot, it
yields to the event loop only if the task has gone 0.5 ms without yielding
(`_driver.YIELD_INTERVAL`). So `async for line in f` over cached data costs
about a microsecond per line and still lets other tasks run.

### Cancellation

Cancelling a task cancels its operation in the kernel (`IORING_OP_ASYNC_CANCEL`),
so reads from pipes and FIFO opens are cancellable where a worker thread
would be stuck. The task then waits for the kernel's verdict before raising,
because the kernel may be writing into the buffer until then.

If the operation turned out to have completed anyway, the cancel lost the
race, and the call returns its result as if it had not been cancelled. The
cancellation is not lost: it is raised at the task's next checkpoint (on
Trio, and on asyncio from an anyio cancel scope, cancellation stays in force
until the scope is left). A call that needs more than one operation, such as
`readline()` going back for more, therefore usually is cancelled, at its next
step. When it is, nothing done so far is lost:

- bytes that were read stay in the file object for the next read;
- bytes that were written are dropped from the write buffer, not written twice;
- a file that was opened is closed again.

asyncio's own cancellation (`Task.cancel()`, `asyncio.timeout`, `wait_for`)
is delivered only once, so swallowing it would lose it. For a completed
write, on Python 3.13 and later, it is put back instead (the task is
cancelled again, to be raised at its next await) and the write returns its
count. If the task ends before awaiting anything, asyncio discards the count
and reports the task cancelled; the data was still written, exactly once. A
small buffered write is the exception: if the flush that made room for it
completed, it raises there, before taking anything. Reads are not treated
this way, since a discarded return value would be lost data. They, and
writes before 3.13, raise the cancellation, with the effect kept as above.

Consequences worth knowing:

- A task whose operation the kernel cannot cancel (a write to disk in
  progress, say) is not cancelled until that operation finishes.
- `cancel_scope.cancelled_caught` is false if the cancelled operation
  completed and nothing after it in the scope checkpointed. Use
  `cancel_called` to ask whether the deadline passed.
- Before Python 3.13, under asyncio's own cancellation, an *unbuffered* write
  that completed anyway raises the cancellation even though the data was
  written; the count is lost.
- A cancelled buffered `write()` of less than the buffer size takes nothing.
  A larger one may have been accepted into the buffer.
- `aclose()` in a cancelled scope still flushes a regular file (shielded),
  then raises. For pipes and terminals, where a flush can block forever, it
  closes without flushing.

### Compared with `open()`

The test suite runs random operation sequences against the builtin file
objects and requires identical results, positions and file contents. The
places where this deliberately differs:

- A handful of C `TextIOWrapper` oddities are not reproduced: `tell()` here
  always returns the canonical (earliest) cookie, `newlines` survives
  `tell()`, `tell()` keeps working after partial iteration. Cookies from
  either implementation seek correctly in the other.
- Opening a FIFO waits for the peer as usual, but is implemented by opening
  it non-blocking and polling, because that is what io_uring's open does
  first. Other special files (devices) are opened by io_uring's rules, i.e.
  as if with `O_NONBLOCK` for the open itself.
- At most 40 operations per thread can be blocked in kernel workers at once
  (`_driver.MAX_WORKERS`); more queue up.

## Performance

`bench/bench.py`, Python 3.13, a 2-vCPU Firecracker VM, ext4. Per-operation
time, and the speedup over `anyio.open_file` on the same backend. "blocking"
is plain `open()` called from the coroutine, i.e. what the work itself costs
if you stall the loop for it.

| workload | uringfile | anyio (threads) | blocking | speedup: asyncio / uvloop / trio |
|---|---|---|---|---|
| open + read + close, 4 KiB files, cached | 89–108 µs | 286–491 µs | 14–21 µs | 4.8× / 3.2× / 4.5× |
| 64 KiB reads through a 64 MiB file, cached | 25–27 µs | 102–176 µs | 9–10 µs | 5.6× / 3.8× / 7.0× |
| iterate 100k text lines | 1.3–1.4 µs | 99–172 µs | 0.22–0.40 µs | 98× / 79× / 126× |
| 100k buffered 50-byte writes | 2.1–2.3 µs | 103–166 µs | 0.29–0.30 µs | 61× / 46× / 79× |
| 16 × 8 MiB files concurrently, cold cache | 52–62 µs | 122–218 µs | 31–40 µs | 3.0× / 2.3× / 3.5× |

Reading the table:

- The two big ratios are not io_uring's doing. anyio hops to a thread for
  every `readline`/`write`; this library answers them from its own buffer.
- One ring operation costs about 7–10 µs here, of which about 4 µs is the
  system call and the rest is Python (`struct` packing, ctypes, bookkeeping).
  A blocking `read()` of cached data is a couple of microseconds. So for
  small cached files, blocking calls are still several times faster; what
  this buys is not stalling the loop when the data is *not* cached, without
  the cost of a thread hop.
- One VM, best of three, no error bars. Treat as order of magnitude. The
  cold-cache row in particular moves by a quarter from one run to the next.
- The cached rows hardly ever wait, so they say nothing about the wait path.
  For an operation that does have to wait (a read from a pipe that another
  task then writes to), one round costs about 41 µs on asyncio, 28 µs on
  uvloop and 43 µs on Trio, loop overhead included.

## Limits and loose ends

- Forking while an event loop is running with operations in flight is not
  supported. (A child forked otherwise gets a fresh ring; the inherited one
  is disabled.)
- The CQ tail is read with a plain load. The io_uring protocol wants an
  acquire load there, which pure Python cannot express. On x86 a plain load
  is one. On weakly ordered CPUs the code relies on the interpreter distance
  between loading the tail and reading the entry, which is an argument, not a
  guarantee. See the comment in `Ring.drain`.
- A finished event loop's ring and eventfd (two descriptors) are released
  when the loop object is freed: at once on asyncio and uvloop, at the next
  garbage collection on Trio, whose run state sits in reference cycles.
- If a ring is torn down with operations still in flight (loop closed under
  running tasks), their buffers are leaked on purpose rather than freed
  under the kernel.
- `mypy` passes with default settings; `--strict` reports `no-any-return`
  inside `AsyncFile`, whose implementation object is typed `Any`.
- No license has been chosen.

## Development

```
pip install -e .[test]
pytest                      # ~8250 tests, most of them differential; a few minutes
python bench/bench.py       # BENCH_DIR=/some/disk to pick the filesystem
ruff check && ruff format --check && mypy src
```

The tests skip themselves where io_uring is unavailable.
