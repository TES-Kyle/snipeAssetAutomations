import tkinter as tk
from tkinter.scrolledtext import ScrolledText
import multiprocessing as mp
import threading
import sys
import time
import os

# Keep track of how many log windows have been opened
_window_counter = 0


def _worker_func(func, log_queue):
    """Runs in a separate process. Redirects print() to a queue."""
    class QueueWriter:
        def write(self, msg):
            if msg.strip():
                log_queue.put(msg)
        def flush(self): pass

    sys.stdout = QueueWriter()
    sys.stderr = QueueWriter()

    try:
        func()
    except Exception as e:
        log_queue.put(f"[[Error: {e}]]")
    finally:
        log_queue.put("[[SCRIPT FINISHED]]")


def handler(func, autoclose_delay=120):
    """Open a new Tk window and run func() in a separate process, showing logs."""

    global _window_counter
    _window_counter += 1

    win = tk.Toplevel()
    win.title(f"Script Log #{_window_counter}")

    # Center on screen
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

    log_queue = mp.Queue()
    proc = mp.Process(target=_worker_func, args=(func, log_queue), daemon=True)
    proc.start()

    finished_flag = threading.Event()

    def poll_log_queue():
        while not log_queue.empty():
            msg = log_queue.get_nowait()

            if msg == "[[SCRIPT FINISHED]]":
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
        finished_flag.set()
        stop_button.config(state="disabled")
        close_button.config(state="normal")
        keep_button.config(state="normal")

        # Countdown + auto-close
        remaining = autoclose_delay

        def update_countdown():
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
        if proc.is_alive():
            proc.terminate()
            log_box.insert(tk.END, "[[Script forcefully terminated]]\n")
            log_box.see(tk.END)
        stop_button.config(state="disabled")
        on_finish()

    def keep_open():
        keep_button.config(state="disabled")
        countdown_label.config(text="Window will stay open permanently")
        log_box.insert(tk.END, "[[Window will stay open permanently]]\n")
        log_box.see(tk.END)

    def on_window_close():
        """Ensure process is killed if user closes the window manually."""
        if proc.is_alive():
            proc.terminate()
            print("[[Script terminated because window was closed]]")
        win.destroy()

    stop_button.config(command=stop_script)
    keep_button.config(command=keep_open)

    # Override the ❌ button in window title bar
    win.protocol("WM_DELETE_WINDOW", on_window_close)

    poll_log_queue()



# Example long-running script
def example_task():
    for i in range(1000):
        print(f"Working... step {i+1}/10 (pid={os.getpid()})")
        time.sleep(0.1)
    print("Task finished!")