"""Atomic offline progress and process lock, outside canonical DB authority."""

import json
import os


class CheckpointFile:
    def __init__(self, root):
        self.path = root / "checkpoint.json"
        self._lock = (root / "worker.lock").open("a+b")
        if self._lock.tell() == 0:
            self._lock.write(b"0")
            self._lock.flush()
        self._lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._lock.close()
            raise RuntimeError("another historical worker owns this rebuild") from None

    def load(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, state):
        temporary = self.path.with_suffix(".pending")
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(state, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    def close(self):
        self._lock.close()  # OS releases the process lock even after a crash.
