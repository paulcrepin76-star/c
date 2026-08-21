from __future__ import annotations

import queue
import threading


class PlaywrightWorker(threading.Thread):
    """All Playwright calls stay on one thread. The library is not thread-safe."""

    def __init__(self):
        super().__init__(daemon=True, name="playwright-worker")
        self._q: queue.Queue = queue.Queue()
        self.start()

    def call(self, fn, *args, timeout: float = 120):
        box: dict = {}
        done = threading.Event()
        self._q.put((fn, args, box, done))
        if not done.wait(timeout):
            return {"ok": False, "error": "browser timed out"}
        if "exc" in box:
            return {"ok": False, "error": str(box["exc"])[:400]}
        return box.get("result")

    def run(self) -> None:
        while True:
            fn, args, box, done = self._q.get()
            try:
                box["result"] = fn(*args)
            except Exception as exc:  # noqa: BLE001
                box["exc"] = exc
            done.set()


worker = PlaywrightWorker()
