"""OS-backed installation locks; a crashed process releases its handles."""
from contextlib import contextmanager
import os
from pathlib import Path
import threading
import time


def data_path(name):
    root = Path(os.environ.get("BIZASSIST_DATA_DIR") or Path(__file__).resolve().parent.parent)
    root.mkdir(parents=True, exist_ok=True)
    return root / name


def _lock(stream, blocking):
    if os.name == "nt":
        import msvcrt
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))


def _unlock(stream):
    if os.name == "nt":
        import msvcrt
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _open(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    if stream.seek(0, 2) == 0:
        stream.write(b"\0")
        stream.flush()
    return stream


@contextmanager
def file_lock(path, timeout=10):
    stream = _open(Path(path))
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                _lock(stream, False)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Another process holds the installation storage lock")
                time.sleep(.02)
        try:
            yield
        finally:
            _unlock(stream)
    finally:
        stream.close()


_lease_lock = threading.Lock()
_leases = {}


def acquire_sync_process_lease():
    """Only one backend process may run sync/listeners for an installation."""
    path = data_path(".sync-worker.lock").resolve()
    key = (os.getpid(), str(path))
    with _lease_lock:
        if key in _leases:
            return True
        stream = _open(path)
        try:
            _lock(stream, False)
        except OSError:
            stream.close()
            return False
        _leases[key] = stream
        return True
