"""``python -m eval_worker`` starts the worker on Windows.

arq's CLI registers ``loop.add_signal_handler``, which Windows does not
support, so development starts the worker through this runner with signal
handling disabled; Ctrl+C still surfaces as ``KeyboardInterrupt``.
"""

from contextlib import suppress

from arq.worker import create_worker

from eval_worker.main import get_worker_kwargs


def main() -> None:
    worker = create_worker(get_worker_kwargs(), handle_signals=False)
    with suppress(KeyboardInterrupt):
        worker.run()


if __name__ == "__main__":
    main()
