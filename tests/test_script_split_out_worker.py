"""Tests for script split-out worker behavior."""

import queue
import sys

from otherManagementFunctions import scriptSplitOutHandler as handler


def test_worker_func_emits_output_and_finish():
    log_queue = queue.Queue()

    def task():
        print("hello from worker")

    old_stdout = sys.stdout
    old_stderr = sys.stderr
    try:
        handler._worker_func(task, log_queue)
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    items = []
    while not log_queue.empty():
        items.append(log_queue.get())

    assert any("hello from worker" in item for item in items)
    assert "[[SCRIPT FINISHED]]" in items
