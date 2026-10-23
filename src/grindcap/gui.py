"""A small control window that stays on top of the game.

Start it with `grindcap gui`, or `grindcap-gui` (no terminal window). It captures the game window
directly, so you don't have to switch windows at the right moment.

  Start snapshot / End snapshot   reads EXP and mesos immediately and shows them
  then open your inventory and scroll through every tab: pages are captured automatically
  (or press Capture page / F8). Press Finish / F10 when done.
  Compare                          EXP/hr, mesos/hr and items, plus the full report
"""
from __future__ import annotations

import queue
import threading
import traceback
import webbrowser
from pathlib import Path


def main(config_path: str = "config.yaml"):
    import tkinter as tk
    from tkinter import ttk

    from .capture import ScreenSource
    from .config import Config

    cfg = Config.load(config_path)
    c = cfg["capture"]
    source = ScreenSource(c["monitor"], c["region"], c["fps"], c.get("window_title"))

    from .app import SnapFlow

    flow = SnapFlow(cfg, source.grab_one)
    jobs: queue.Queue = queue.Queue()     # results from worker threads -> UI thread

    root = tk.Tk()
    root.title("grindcap")
    root.attributes("-topmost", True)
    root.resizable(False, False)
    root.geometry("+20+20")

    status = tk.StringVar(value="Ready. Keep the game open (it can be behind other windows).")
    readout = tk.StringVar(value="")
    auto = tk.BooleanVar(value=True)

    frm = ttk.Frame(root, padding=8)
    frm.grid()
    ttk.Label(frm, textvariable=status, wraplength=300, justify="left").grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(frm, textvariable=readout, wraplength=300, justify="left", font=("Consolas", 9)).grid(
        row=1, column=0, columnspan=3, sticky="w", pady=(4, 6))

    b_start = ttk.Button(frm, text="Start snapshot", command=lambda: begin("start"))
    b_end = ttk.Button(frm, text="End snapshot", command=lambda: begin("end"))
    b_cmp = ttk.Button(frm, text="Compare", command=lambda: run_bg(do_compare))
    b_page = ttk.Button(frm, text="Capture page (F8)", command=lambda: run_bg(do_page))
    b_fin = ttk.Button(frm, text="Finish (F10)", command=lambda: run_bg(do_finish))
    b_cancel = ttk.Button(frm, text="Cancel", command=lambda: cancel())
    b_review = ttk.Button(frm, text="Review / fix sessions", command=lambda: review())
    chk = ttk.Checkbutton(frm, text="Capture pages automatically as I scroll", variable=auto)

    def layout(collecting: bool):
        for w in (b_start, b_end, b_cmp, b_page, b_fin, b_cancel, chk, b_review):
            w.grid_remove()
        if collecting:
            b_page.grid(row=2, column=0, sticky="ew", padx=2)
            b_fin.grid(row=2, column=1, sticky="ew", padx=2)
            b_cancel.grid(row=2, column=2, sticky="ew", padx=2)
            chk.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
        else:
            b_start.grid(row=2, column=0, sticky="ew", padx=2)
            b_end.grid(row=2, column=1, sticky="ew", padx=2)
            b_cmp.grid(row=2, column=2, sticky="ew", padx=2)
            b_review.grid(row=3, column=0, columnspan=3, sticky="ew", padx=2, pady=(4, 0))

    # --- work that touches the screen or OCR runs off the UI thread ---
    busy = threading.Lock()

    waiting: list = []  # button presses waiting for the current background job to end

    def run_bg(fn, *args, retry: bool = True):
        if not busy.acquire(blocking=False):
            if retry:  # something is running; run this as soon as it ends, before any more polling
                waiting.append((fn, args))
            return

        def work():
            try:
                jobs.put(("ok", fn(*args)))
            except Exception as e:  # show the problem in the window instead of crashing
                traceback.print_exc()
                jobs.put(("err", str(e)))
            finally:
                busy.release()
        threading.Thread(target=work, daemon=True).start()

    def do_start(which):
        st = flow.start(which)
        exp = st.get("exp")
        mes = st.get("mesos")
        return ("started", which, f"EXP {exp if exp is not None else '?'}   Level {st.get('level') or '?'}   "
                                  f"Mesos {mes if mes is not None else '?'}   (via {source.method})")

    def do_page():
        return ("page", flow.add_page())

    def do_finish():
        return ("finished", flow.finish())

    def do_compare():
        return ("compared",) + flow.compare()

    server = {}

    def review(session_id=None):
        """Open the review page in the browser (one local server, started on first use)."""
        from .review import serve

        try:
            if "httpd" not in server:
                server["httpd"] = serve(cfg, open_browser=False)
            url = server["httpd"].url + (f"?session={session_id}" if session_id else "")
            webbrowser.open(url)
            status.set("Review page opened in your browser. Fixes are saved as you make them.")
        except Exception as e:
            status.set(f"Problem: {e}")

    def begin(which):
        run_bg(do_start, which)

    def cancel():
        flow.cancel()
        status.set("Cancelled.")
        layout(False)

    def handle(result):
        kind = result[0]
        if kind == "idle":
            return
        if kind == "started":
            _, which, line = result
            readout.set(line)
            status.set(f"{which.title()} snapshot: open your inventory and scroll through every tab, top to "
                       "bottom. Pages are captured as you go. Press Finish when done.")
            layout(True)
        elif kind == "page":
            status.set(f"Captured {result[1]} page(s). Keep scrolling, or press Finish.")
        elif kind == "finished":
            info = result[1]
            layout(False)
            status.set(f"Saved the {info['which']} snapshot ({info['pages']} pages, {info['kinds']} kinds of item, "
                       f"{info['count']} items in total).")
            readout.set(f"EXP {info['exp']}   Level {info['level']}   Mesos {info['mesos']}")
            if info["which"] == "end":
                status.set(status.get() + " Press Compare, or Review / fix to check what changed.")
        elif kind == "compared":
            _, text, report = result
            show_text("Comparison", text, report)

    def show_text(title, text, report=None):
        win = tk.Toplevel(root)
        win.title(title)
        win.attributes("-topmost", True)
        t = tk.Text(win, width=78, height=26, font=("Consolas", 9))
        t.insert("1.0", text)
        t.configure(state="disabled")
        t.pack(padx=6, pady=6)
        if report:
            ttk.Button(win, text="Review and fix what changed",
                       command=lambda: review(Path(report).parent.name)).pack(pady=(0, 4))
            ttk.Button(win, text="Open report with item icons",
                       command=lambda: webbrowser.open(report.resolve().as_uri())).pack(pady=(0, 6))

    # --- periodic: deliver results, and auto-capture pages while collecting ---
    def tick():
        try:
            while True:
                kind, payload = jobs.get_nowait()
                if kind == "err":
                    status.set(f"Problem: {payload}")
                else:
                    handle(payload)
        except queue.Empty:
            pass
        if waiting and not busy.locked():
            fn, args = waiting.pop(0)
            run_bg(fn, *args)
        elif flow.collecting and auto.get() and not busy.locked():
            def poll():
                return ("page", len(flow.pages)) if flow.poll() else ("idle",)
            run_bg(poll, retry=False)
        root.after(400, tick)

    # --- global hotkeys, usable from inside the game ---
    try:
        from pynput import keyboard

        def on_press(key):
            if not flow.collecting:
                return
            if key == keyboard.Key.f8:
                root.after(0, lambda: run_bg(do_page))
            elif key == keyboard.Key.f10:
                root.after(0, lambda: run_bg(do_finish))

        keyboard.Listener(on_press=on_press, daemon=True).start()
    except Exception:
        pass

    layout(False)
    root.after(400, tick)
    root.protocol("WM_DELETE_WINDOW", lambda: (source.game.close() if source.game else None, root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
