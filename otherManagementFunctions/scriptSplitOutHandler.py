"""Run long tasks in a separate process and stream logs to a Tk window."""

import logging
import multiprocessing as mp
import os
import sys
import threading
import time
import tkinter as tk
from tkinter.scrolledtext import ScrolledText

from utilities.logging_utils import configure_logging, get_settings

logger = logging.getLogger(__name__)

# Keep track of how many log windows have been opened
_window_counter = 0


def _worker_func(func, log_queue):
    """Run a function in a separate process and stream logs to a queue.

    Args:
        func: Callable to execute in a worker process.
        log_queue: Multiprocessing queue for log messages.
    """
    class QueueWriter:
        """File-like adapter that forwards writes into the log queue."""
        def write(self, msg):
            """Write non-empty messages to the queue."""
            if msg.strip():
                log_queue.put(msg)
        def flush(self):
            """No-op flush to satisfy file-like interface."""
            pass

    # Redirect stdout into the queue to capture print() calls.
    # sys.stderr is intentionally left alone — QueueLogHandler already routes
    # Python log messages to the queue, and replacing sys.stderr here would cause
    # duplicate lines (once via StderrStreamHandler→QueueWriter, once via QueueLogHandler).
    sys.stdout = QueueWriter()

    try:
        # Configure logging inside the subprocess to mirror into the queue.
        configure_logging(log_queue=log_queue)
        func()
    except Exception as e:
        logger.exception("Worker function failed")
        log_queue.put(f"[[Error: {e}]]")
    finally:
        # Always signal completion so the UI can stop polling.
        log_queue.put("[[SCRIPT FINISHED]]")


def handler(func, autoclose_delay=120):
    """Open a new Tk window and run func() in a separate process, showing logs.

    Args:
        func: Callable to execute.
        autoclose_delay: Default auto-close delay in seconds.
    """
    settings = get_settings()
    try:
        autoclose_delay = int(settings.get("logWindowAutocloseSeconds", autoclose_delay))
    except Exception:
        autoclose_delay = autoclose_delay

    global _window_counter
    _window_counter += 1

    win = tk.Toplevel()
    win.title(f"Script Log #{_window_counter}")

    # Center on screen.
    win.update_idletasks()
    w, h = 600, 400
    x = (win.winfo_screenwidth() // 2) - (w // 2)
    y = (win.winfo_screenheight() // 2) - (h // 2)
    win.geometry(f"{w}x{h}+{x}+{y}")

    log_box = ScrolledText(win, height=20, width=80, state="normal")
    log_box.pack(padx=10, pady=10, fill="both", expand=True)

    button_frame = tk.Frame(win)
    button_frame.pack(fill="x", pady=5)

    stop_button = tk.Button(button_frame, text="Stop Script", state="normal")
    stop_button.pack(side="left", padx=5)

    close_button = tk.Button(button_frame, text="Close Now", state="disabled", command=win.destroy)
    close_button.pack(side="right", padx=5)

    keep_button = tk.Button(button_frame, text="Keep Open", state="disabled")
    keep_button.pack(side="right", padx=5)

    # Countdown label
    countdown_label = tk.Label(win, text="")
    countdown_label.pack(side="bottom", pady=3)

    # Start the worker process and set up polling for logs.
    log_queue = mp.Queue()
    proc = mp.Process(target=_worker_func, args=(func, log_queue), daemon=True)
    proc.start()

    finished_flag = threading.Event()

    def poll_log_queue():
        """Drain the log queue and update the log window."""
        while not log_queue.empty():
            msg = log_queue.get_nowait()

            if msg == "[[SCRIPT FINISHED]]":
                # Move the UI into finished state and start auto-close.
                on_finish()
            else:
                # Check if scrollbar is at the bottom
                at_bottom = log_box.yview()[1] == 1.0

                log_box.insert(tk.END, msg + "\n")

                # Only auto-scroll if already at bottom
                if at_bottom:
                    log_box.see(tk.END)

        if not finished_flag.is_set():
            win.after(100, poll_log_queue)

    def on_finish():
        """Finalize UI state and trigger auto-close countdown."""
        finished_flag.set()
        stop_button.config(state="disabled")
        close_button.config(state="normal")
        keep_button.config(state="normal")

        # Countdown + auto-close
        remaining = autoclose_delay

        def update_countdown():
            """Update the auto-close countdown label once per second."""
            nonlocal remaining
            if keep_button["state"] == "disabled":  # "Keep Open" was pressed
                countdown_label.config(text="Window will stay open permanently")
                return
            if remaining > 0:
                countdown_label.config(text=f"Auto-closing in {remaining}s...")
                remaining -= 1
                win.after(1000, update_countdown)
            else:
                if win.winfo_exists():
                    win.destroy()

        update_countdown()

    def stop_script():
        """Terminate the worker process and update UI/logs."""
        if proc.is_alive():
            proc.terminate()
            log_box.insert(tk.END, "[[Script forcefully terminated]]\n")
            log_box.see(tk.END)
        stop_button.config(state="disabled")
        on_finish()

    def keep_open():
        """Disable auto-close and keep the log window open."""
        keep_button.config(state="disabled")
        countdown_label.config(text="Window will stay open permanently")
        log_box.insert(tk.END, "[[Window will stay open permanently]]\n")
        log_box.see(tk.END)

    def on_window_close():
        """Ensure process is killed if user closes the window manually."""
        if proc.is_alive():
            proc.terminate()
            logger.warning("Script terminated because window was closed")
        win.destroy()

    stop_button.config(command=stop_script)
    keep_button.config(command=keep_open)

    # Override the ❌ button in window title bar
    win.protocol("WM_DELETE_WINDOW", on_window_close)

    poll_log_queue()



# Example long-running script
def example_task():
    """Example long-running task used for manual testing."""
    for i in range(1000):
        logger.info("Working... step %s/10 (pid=%s)", i + 1, os.getpid())
        time.sleep(0.1)
    logger.info("Task finished!")
