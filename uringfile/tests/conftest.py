from __future__ import annotations

import gc
import os
import re
import tempfile
from pathlib import Path

import pytest

import uringfile

if not uringfile.available():
    pytest.skip("io_uring is not available here", allow_module_level=True)

_backends = [
    pytest.param(("asyncio", {}), id="asyncio"),
    pytest.param(("trio", {}), id="trio"),
]
try:
    import uvloop  # noqa: F401
except ImportError:
    pass
else:
    _backends.insert(1, pytest.param(("asyncio", {"use_uvloop": True}), id="uvloop"))


@pytest.fixture(params=_backends)
def anyio_backend(request):
    return request.param


@pytest.fixture
def tmp_path(request, tmp_path_factory):
    """pytest's tmp_path, without the cost that grows with the suite.

    pytest numbers each test's directory by listing every directory made so
    far, and over thousands of tests that came to a third of the run time.
    These go in the same place, under names mkdtemp picks.
    """
    prefix = re.sub(r"\W", "_", request.node.name)[:30] + "-"
    return Path(tempfile.mkdtemp(prefix=prefix, dir=tmp_path_factory.getbasetemp()))


@pytest.fixture
def path(tmp_path):
    """A path for a scratch file (not created)."""
    return str(tmp_path / "file")


@pytest.fixture
def fifo():
    """A pipe as ``(read_fd, write_fd)``; closed afterwards if still open."""
    r, w = os.pipe()
    yield r, w
    for fd in (r, w):
        try:
            os.close(fd)
        except OSError:
            pass


@pytest.fixture
def count_fds():
    """Return a function counting this process's open descriptors."""

    def count():
        gc.collect()
        return len(os.listdir("/proc/self/fd"))

    return count
