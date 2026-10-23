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
import time
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
    b_fin = ttk.Button(frm, text="Finish (F10)", command=lambda: finish_now())
    b_cancel = ttk.Button(frm, text="Cancel", command=lambda: cancel())
    b_review = ttk.Button(frm, text="Review / fix sessions", command=lambda: review())
    b_discard = ttk.Button(frm, text="Discard", command=lambda: discard())
    timer = tk.StringVar(value="")
    timer_lbl = ttk.Label(frm, textvariable=timer, font=("Segoe UI", 11, "bold"))
    session = {"run": None}   # the start snapshot waiting for its end, if any
    processing = {"on": False}  # a finished snapshot is being read in the background

    def refresh_running():
        from .sessions import running

        try:
            session["run"] = running(cfg["inventory"]["snapshot_dir"])
        except Exception:
            session["run"] = None
    chk = ttk.Checkbutton(frm, text="Capture pages automatically as I scroll", variable=auto)

    def layout(collecting: bool):
        for w in (b_start, b_end, b_cmp, b_page, b_fin, b_cancel, chk, b_review, timer_lbl, b_discard):
            w.grid_remove()
        if processing["on"]:
            # reading the pages: nothing to press; the session timer already runs for a start snapshot
            if session["run"]:
                timer_lbl.grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
            update_timer()
            return
        if collecting:
            b_page.grid(row=2, column=0, sticky="ew", padx=2)
            b_fin.grid(row=2, column=1, sticky="ew", padx=2)
            b_cancel.grid(row=2, column=2, sticky="ew", padx=2)
            chk.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
        else:
            refresh_running()
            run = session["run"]
            b_start.grid(row=2, column=0, sticky="ew", padx=2)
            b_end.grid(row=2, column=1, sticky="ew", padx=2)
            b_cmp.grid(row=2, column=2, sticky="ew", padx=2)
            b_review.grid(row=3, column=0, columnspan=3, sticky="ew", padx=2, pady=(4, 0))
            # One session at a time: while one is running, Start is greyed out and a timer shows.
            b_start.state(["disabled"] if run else ["!disabled"])
            b_end.state(["!disabled"] if run else ["disabled"])
            if run:
                timer_lbl.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
                b_discard.grid(row=4, column=2, sticky="e", pady=(6, 0))
            update_timer()

    def update_timer():
        run = session["run"]
        if not run:
            timer.set("")
            return
        secs = int(time.time() - run["time"])
        where = f" · {run['map']}" if run.get("map") else ""
        timer.set(f"Session running {secs // 3600}:{secs % 3600 // 60:02d}:{secs % 60:02d}{where}")

    def discard():
        """Throw away a start snapshot taken by mistake, so a new session can be started."""
        import shutil
        from tkinter import messagebox

        run = session["run"]
        if run and messagebox.askyesno("Discard session", "Discard the running session's start snapshot?",
                                       parent=root):
            shutil.rmtree(run["folder"], ignore_errors=True)
            status.set("Discarded. Start a new session when you're ready.")
            layout(False)

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
        where = (st.get("map") or {}).get("name") or "map not read"
        return ("started", which, f"EXP {exp if exp is not None else '?'}   Level {st.get('level') or '?'}   "
                                  f"Mesos {mes if mes is not None else '?'}\n{where}   (via {source.method})")

    def do_page():
        return ("page", flow.add_page())

    def do_finish():
        return ("finished", flow.finish(progress=lambda text: jobs.put(("ok", ("progress", text)))))

    def finish_now():
        """Stop collecting pages and read them in the background. For a start snapshot the session
        clock starts now (at the last page), not when reading is done."""
        if not flow.collecting or processing["on"]:
            return
        processing["on"] = True
        if flow.which == "start":
            session["run"] = {"time": flow.grind_time(), "map": (flow.status.get("map") or {}).get("name")}
        else:
            session["run"] = None                 # the session ended when End was pressed
        readout.set("")
        status.set(f"Got {len(flow.pages)} page(s). Reading them now; this can take a few seconds the first "
                   "time new items show up.")
        layout(False)
        run_bg(do_finish)

    def tabs_line() -> str:
        need = flow.needed_tabs
        marks = "  ".join(f"{t} {'✓' if t in flow.tabs_seen else '·'}" for t in need)
        left = flow.finish_in()
        if left is None:
            return f"Tabs: {marks}"
        return f"Tabs: {marks}\nAll tabs in. Finishing in {left:.0f} s (keep scrolling to add pages)."

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
            status.set(f"{which.title()} snapshot: open your inventory and go through every tab, top to "
                       "bottom. Pages are captured as you go, and it finishes by itself a few seconds after "
                       "every tab has been seen (or press Finish).")
            layout(True)
        elif kind == "page":
            status.set(f"Captured {result[1]} page(s). Keep scrolling, or press Finish.")
            readout.set(tabs_line())
        elif kind == "progress":
            status.set(result[1] + "...")
        elif kind == "finished":
            info = result[1]
            processing["on"] = False
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
                    status.set(f"Problem: {payload} You can just try again.")
                    if processing["on"]:          # reading failed: back to collecting, pages kept
                        processing["on"] = False
                        layout(flow.collecting)
                else:
                    handle(payload)
        except queue.Empty:
            pass
        if not flow.collecting or processing["on"]:
            update_timer()
        elif not processing["on"]:
            readout.set(tabs_line())
            left = flow.finish_in()
            if auto.get() and left is not None and left <= 0:
                finish_now()                      # every tab captured and nothing new for a few seconds
        if waiting and not busy.locked():
            fn, args = waiting.pop(0)
            run_bg(fn, *args)
        elif flow.collecting and not processing["on"] and auto.get() and not busy.locked():
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
                root.after(0, finish_now)

        keyboard.Listener(on_press=on_press, daemon=True).start()
    except Exception:
        pass

    layout(False)
    root.after(400, tick)
    root.protocol("WM_DELETE_WINDOW", lambda: (source.game.close() if source.game else None, root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
