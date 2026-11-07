"""``python -m eval_worker`` starts the worker on Windows.

arq's CLI registers ``loop.add_signal_handler``, which Windows does not
support, so development starts the worker through this runner with signal
handling disabled; Ctrl+C still surfaces as ``KeyboardInterrupt``. arq's job
log lines contain non-cp1252 glyphs, so the console streams are switched to
UTF-8 with backslash escaping to keep those lines printable on Windows.
"""

import io
import sys
from contextlib import suppress

from arq.worker import create_worker

from eval_worker.main import get_worker_kwargs


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    worker = create_worker(get_worker_kwargs(), handle_signals=False)
    with suppress(KeyboardInterrupt):
        worker.run()


if __name__ == "__main__":
    main()
