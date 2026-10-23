"""grindcap command line.

  grindcap calibrate              drag boxes around HP, MP, EXP and mesos on a screenshot
  grindcap snapshot               save a screenshot, the box overlay and each crop (for checking)
  grindcap watch                  print live readings so you can check calibration
  grindcap run                    track a live session (Ctrl+C to stop) and print a summary
  grindcap replay VIDEO           run the tracker on a screen recording
  grindcap summarize SESSION      summarise a saved session log
  grindcap export SESSION         print the values to paste into Grind Ledger

Easiest: grindcap gui   (or the grindcap-gui program) opens a small window that stays on top of the game.

Before/after mode (simpler, no live tracking):
  grindcap snap start             capture EXP and mesos, then page through your inventory (F8/F9/F10)
  grindcap snap end               same, after grinding
  grindcap compare                EXP/hr, mesos/hr and every item gained or used, per hour
  grindcap review [SESSION]       fix misread items, names and prices of a session (browser page)
  grindcap reread [FOLDER...]     read saved snapshots again from their screenshots (after an update)
  grindcap teach-digits           check the stack numbers it reads, correct any that are wrong
  grindcap items                  list known item icons and their names/prices
  grindcap identify               name items by matching their icons with the game's item data
  grindcap label ITEM-ID          give an item id a name and price
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .capture import ScreenSource, VideoSource
from .config import Config
from .session import (Tracker, default_session_path, format_summary, ledger_export, load_events,
                      read_values, summarize)

QUIET = {"hp_regen", "mp_regen"}


def _screen(cfg) -> ScreenSource:
    c = cfg["capture"]
    return ScreenSource(c["monitor"], c["region"], c["fps"], c.get("window_title"))


def cmd_windows(cfg, a):
    from .winfind import find_game, list_windows

    wins = list_windows()
    if not wins:
        print("No windows listed (this only works on Windows).")
    for title, r, _ in wins:
        print(f"{r['width']:>5}x{r['height']:<5} at ({r['left']}, {r['top']})  {title}")
    t = cfg["capture"].get("window_title")
    if t:
        from .winfind import find_game_window

        hit = find_game_window(t)
        print(f"\ncapture.window_title = {t!r} -> " + (f"uses the window titled {hit[1]!r}" if hit else "NOT found"))


def cmd_test_capture(cfg, a):
    """Try each way of capturing the game window, save what each one got, and say what happened."""
    import cv2

    src = _screen(cfg)
    out = Path("captures")
    out.mkdir(exist_ok=True)
    if src.game is not None:
        print("Testing capture methods (keep the game open and NOT minimized; it can be behind other windows):")
        for method, img, msg in src.game.diagnose():
            line = f"  {method:<12} {msg}"
            if img is not None:
                p = out / f"test_{method}.png"
                cv2.imwrite(str(p), img)
                line += f"   -> saved {p}"
            print(line)
        print()
    from .wincap import CaptureError

    try:
        img = src.grab_one()
    except CaptureError as e:
        print(f"Normal capture failed: {e}")
        return
    p = out / "test_capture.png"
    cv2.imwrite(str(p), img)
    title = src.game.window_title if src.game and src.game.window_title else "(screen)"
    print(f"Captured {img.shape[1]}x{img.shape[0]} of {title!r} using '{src.method}'. Saved {p}")
    if src.method == "screen":
        print("That was a plain screenshot: it only shows the game when the game is in front. "
              "Install windows-capture (pip install windows-capture) to capture it behind other windows.")


def cmd_gui(cfg, a):
    from .gui import main as gui_main

    gui_main(a.config)


def _print_event(e):
    if e.kind in QUIET:
        return
    extra = " ".join(f"{k}={v}" for k, v in e.data.items())
    print(f"{e.t:8.2f}s  {e.kind:<10} {extra}")


def cmd_calibrate(cfg, a):
    from .calibrate import calibrate, load_frame

    frame = load_frame(a.image, a.video, a.at, _screen(cfg))
    print("Progress is saved after every step. Press C to skip a step you've already done.")
    try:
        calibrate(cfg, frame, a.only, save=lambda: cfg.save(a.config))
    except KeyboardInterrupt:
        print("\nStopped. Everything up to the last finished step is saved.")
        return
    print(f"Saved {cfg.save(a.config)}")


def cmd_snapshot(cfg, a):
    from .calibrate import load_frame, save_snapshot
    from .readers import build_readers

    frame = load_frame(a.image, a.video, a.at, _screen(cfg))
    readings = read_values(build_readers(cfg), frame)
    folder = save_snapshot(cfg, frame, readings)
    print(f"Readings: {readings}\nSaved images to {folder}/")


def cmd_watch(cfg, a):
    from .readers import build_readers

    readers = build_readers(cfg)
    print("Live readings (Ctrl+C to stop)")
    try:
        for t, frame in _screen(cfg).frames():
            vals = read_values(readers, frame)
            print(f"\r{t:7.1f}s  " + "  ".join(f"{k}={v}" for k, v in vals.items()) + " " * 10, end="")
    except KeyboardInterrupt:
        print()


def _track(cfg, source, out, max_seconds=None):
    tr = Tracker(cfg, source, out, on_event=_print_event)
    print(f"Tracking {cfg['session']['monster']}. Logging to {out}. Press Ctrl+C to stop.")
    events = tr.run(max_seconds)
    print("\n" + format_summary(summarize(events)))
    return events


def cmd_run(cfg, a):
    _track(cfg, _screen(cfg), Path(a.out) if a.out else default_session_path(cfg), a.seconds)


def cmd_replay(cfg, a):
    src = VideoSource(a.video, cfg["capture"]["fps"], cfg["capture"]["region"] if a.crop else None)
    _track(cfg, src, Path(a.out) if a.out else default_session_path(cfg), a.seconds)


def cmd_summarize(cfg, a):
    header, events = load_events(a.session)
    s = summarize(events)
    print(json.dumps(s, indent=2) if a.json else format_summary(s))


def cmd_export(cfg, a):
    header, events = load_events(a.session)
    print(json.dumps(ledger_export(header, summarize(events)), indent=2))


def _catalog(cfg):
    from .inventory import Catalog

    return Catalog(cfg["inventory"]["catalog_dir"])


def cmd_snap(cfg, a):
    from .calibrate import load_frame
    from .snapshot import PageCollector, build_snapshot, save_snapshot

    screen = _screen(cfg)
    if a.image or a.video:
        status = load_frame(a.image, a.video, a.at, screen)
        pages = {"Inventory": [status]}
    else:
        print("Make sure your EXP and meso total are visible. Capturing status in 2 s...")
        time.sleep(2)
        status = screen.grab_one()
        pages = PageCollector(screen.grab_one, cfg["inventory"]["tabs"]).run()
    cat = _catalog(cfg)
    snap = build_snapshot(cfg, status, pages, cat)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    folder = save_snapshot(snap, Path(cfg["inventory"]["snapshot_dir"]) / f"{a.which}-{stamp}", status, pages)
    n_items = sum(snap["items"].values())
    print(f"Saved {folder}: level {snap['level']}, EXP {snap['exp']}, mesos {snap['mesos']}, "
          f"{len(snap['items'])} different items ({n_items} total)")
    if snap["exp"] is None:
        print("  EXP was not read. Check the exp box with `grindcap snapshot`.")


def cmd_compare(cfg, a):
    from .snapshot import compare, format_compare, html_report, latest_snapshot, load_snapshot

    root = Path(cfg["inventory"]["snapshot_dir"])
    start = a.start or latest_snapshot(root, "start")
    end = a.end or latest_snapshot(root, "end")
    if not start or not end:
        raise SystemExit("Need a start and an end snapshot. Run `grindcap snap start` and `grindcap snap end`.")
    cat = _catalog(cfg)
    r = compare(load_snapshot(start), load_snapshot(end), cat, a.minutes)
    print(f"Comparing {start} -> {end}\n")
    print(json.dumps(r, indent=2) if a.json else format_compare(r))
    out = Path(end) / "report.html"
    html_report(r, cat, out)
    print(f"\nReport with item icons: {out}")


def cmd_reread(cfg, a):
    """Read saved snapshots again from their screenshots (after a fix), keeping their times."""
    import cv2

    from .snapshot import build_snapshot, latest_snapshot, load_snapshot

    root = Path(cfg["inventory"]["snapshot_dir"])
    folders = [Path(f) for f in a.folders] or [f for f in (latest_snapshot(root, "start"),
                                                           latest_snapshot(root, "end")) if f]
    if not folders:
        raise SystemExit("No snapshots found.")
    for folder in folders:
        old = load_snapshot(folder)
        status = cv2.imread(str(folder / "status.png")) if (folder / "status.png").exists() else None
        pages: dict[str, list] = {}
        for png in sorted(folder.glob("*_[0-9][0-9].png")):
            tab = png.stem.rsplit("_", 1)[0]
            pages.setdefault(tab, []).append(cv2.imread(str(png)))
        snap = build_snapshot(cfg, status, pages, _catalog(cfg), when=old["time"])
        (folder / "snapshot.json").write_text(json.dumps(snap, indent=2))
        n = sum(len(v) for v in pages.values())
        print(f"{folder}: {n} pages, {len(snap['items'])} kinds of item, "
              f"{sum(snap['items'].values())} items (was {sum(old['items'].values())})")
        for tab, log in snap.get("merge_log", {}).items():
            print(f"  {tab}:")
            for line in log:
                print(f"    {line}")
        for tab, n in (snap.get("skipped_tabs") or {}).items():
            print(f"  {tab}: {n} page(s) not counted (inventory.skip_tabs)")


def cmd_itemdb(cfg, a):
    """Download (or update) item names and icons from maplestory.io."""
    from .snapshot import open_itemdb

    db = open_itemdb(cfg, download=False)
    if db is None or a.update:
        from .itemdb import ItemDB

        opt = cfg["inventory"].get("itemdb") or {}
        db = ItemDB(Path(cfg["inventory"]["catalog_dir"]) / "itemdb", opt.get("region", "MCW"),
                    str(opt.get("version", "1")))
        db.download()
    else:
        print(f"Item data already downloaded: {len(db.items)} items in {db.folder}. Use --update to refresh.")


def cmd_identify(cfg, a):
    """Name catalog items from the item database by their saved icons."""
    import cv2

    from .digits import native_scale, native_view
    from .inventory import Grid
    from .snapshot import open_itemdb

    db = open_itemdb(cfg)
    if db is None:
        raise SystemExit("No item data. Check your internet connection and run `grindcap itemdb`.")
    cat = _catalog(cfg)
    grid = Grid.from_cfg(cfg["inventory"])
    named = 0
    for iid, info in cat.items.items():
        if info.get("name") and not (a.all and info.get("db")):
            continue
        img = cv2.imread(str(cat.icons_dir / f"{iid}.png"))
        if img is None:
            continue
        sx, sy = native_scale(grid.pitch()[0], (1080, 1920) if a.frame_h is None else (a.frame_h, a.frame_h * 16 // 9))
        view = native_view(img, (0, 0, img.shape[1], img.shape[0]), sx, sy, color=True)
        patch = cv2.copyMakeBorder(view.color, 4, 4, 4, 4, cv2.BORDER_REPLICATE)
        m = db.identify(patch)
        if m:
            cat.set_identity(iid, m, db.price(m.item_id))
            named += 1
            print(f"{iid}: {m.name}  (score {m.score:.0f}, next best {m.runner_up} is {m.ratio:.2f}x worse)")
        else:
            best = db.rank(patch)[:3]
            print(f"{iid}: not sure. Closest: " + ", ".join(db.items[i]["name"] for _, i in best))
    print(f"Named {named} items. Name the rest with `grindcap label ITEM-ID --name ...`.")


def cmd_review(cfg, a):
    """Open the review page (fix misread items, set prices) and keep it running until Ctrl+C."""
    from .review import serve

    httpd = serve(cfg, a.session, open_browser=not a.no_browser, port=a.port)
    print(f"Review page: {httpd.url}  (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        httpd.shutdown()


def cmd_items(cfg, a):
    cat = _catalog(cfg)
    if not cat.items:
        print("No items yet. Take a snapshot first.")
    for iid, info in cat.items.items():
        pr = cat.price(iid)
        src = "yours" if info.get("price") is not None else ("NPC" if pr is not None else "")
        print(f"{iid}  {info.get('name') or '(no name)':<28} price {pr if pr is not None else '-'} {src:<5}"
              f"   icon: {cat.icons_dir / (iid + '.png')}")


def cmd_label(cfg, a):
    cat = _catalog(cfg)
    cat.label(a.item, a.name, a.price)
    if a.npc_price:
        cat.items[a.item]["price"] = None
        cat.save()
    print(f"{a.item}: {cat.items[a.item]}")


def readings_sheet(frame, grid, readings, empty, scale: int = 3):
    """One picture of every occupied slot with the number grindcap read under it (r1c1 = row 1, col 1)."""
    import cv2
    import numpy as np

    tiles = []
    for r, row in enumerate(grid.slot_boxes()):
        line = []
        for c, (x, y, w, h) in enumerate(row):
            i = r * grid.cols + c
            img = frame[max(0, y):y + h, max(0, x):x + w]
            tile = np.full((h * scale + 26, w * scale, 3), 30, np.uint8)
            if img.size:
                tile[:img.shape[0] * scale, :img.shape[1] * scale] = cv2.resize(
                    img, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
            if not empty[i]:
                v = readings[i].value
                cv2.putText(tile, f"r{r + 1}c{c + 1}: {v if v is not None else '-'}", (3, h * scale + 19),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 255, 80), 1, cv2.LINE_AA)
            line.append(cv2.copyMakeBorder(tile, 2, 2, 2, 2, cv2.BORDER_CONSTANT, value=(0, 0, 0)))
        tiles.append(np.hstack(line))
    return np.vstack(tiles)


def cmd_teach_digits(cfg, a):
    """Read every stack number, show what was read, and learn from your corrections."""
    import re

    import cv2

    from .anchors import shifted
    from .calibrate import load_frame
    from .digits import StackDigits
    from .inventory import Grid, is_empty

    frame = load_frame(a.image, a.video, a.at, None if (a.image or a.video) else _screen(cfg))
    try:
        cfg = shifted(cfg, frame, ("inventory",))
    except LookupError:
        print("(Couldn't find the inventory landmark; using the calibrated position as is.)")
    inv = cfg["inventory"]
    grid = Grid.from_cfg(inv)
    sd = StackDigits(Path(inv["catalog_dir"]) / "digits.npz")
    boxes = [b for row in grid.slot_boxes() for b in row]
    readings = sd.read_slots(frame, boxes, *grid.pitch())
    empty = [is_empty(frame[max(0, y):y + h, max(0, x):x + w], grid.qty_box, inv["empty_std"])
             for (x, y, w, h) in boxes]
    outdir = Path("captures") / "slots"
    outdir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(outdir / "frame.png"), frame)
    sheet = readings_sheet(frame, grid, readings, empty)
    sheet_png = outdir / "readings.png"
    cv2.imwrite(str(sheet_png), sheet)
    print(f"Read {sum(not e for e in empty)} occupied slots ({grid.cols} columns x {grid.rows} rows). "
          f"Picture: {sheet_png}")
    for r in range(grid.rows):
        print("  " + "  ".join(
            f"{'.' if empty[r * grid.cols + c] else (readings[r * grid.cols + c].value or '-'):>5}"
            for c in range(grid.cols)))
    if not a.image or a.ask:
        cv2.imshow("what grindcap read (any key to close)", sheet)
        cv2.waitKey(1)
    print("\nIf every number is right, press Enter. Otherwise type the right ones, e.g.  r1c4=59 r3c2=52")
    print("(use - for a slot that has no number, e.g. r2c1=-). If the grid itself is wrong, run "
          "`grindcap calibrate --only inventory`.")
    ans = input("> ").strip() if not a.yes else ""
    cv2.destroyAllWindows()
    labels = ["" if e else (str(rd.value) if rd.value is not None else "") for rd, e in zip(readings, empty)]
    fixed = 0
    for r, c, v in re.findall(r"r(\d+)\s*c(\d+)\s*=\s*(\d+|-)", ans.lower()):
        i = (int(r) - 1) * grid.cols + int(c) - 1
        if 0 <= i < len(labels):
            labels[i] = "" if v == "-" else str(int(v))
            fixed += 1
    n = sd.teach(frame, boxes, labels, *grid.pitch())
    sd.save()
    print(f"Learned {n} digits from {sum(bool(l) for l in labels)} slots ({fixed} corrected). Saved {sd.path}.")


def main(argv=None):
    p = argparse.ArgumentParser(prog="grindcap", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default="config.yaml", help="config file (default: config.yaml)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def frame_args(sp):
        sp.add_argument("--image", help="use a screenshot file instead of the live screen")
        sp.add_argument("--video", help="use a frame from a screen recording")
        sp.add_argument("--at", type=float, default=0.0, help="seconds into --video")

    sp = sub.add_parser("calibrate", help="set the HP/MP/EXP/meso boxes")
    frame_args(sp)
    sp.add_argument("--only", nargs="+", choices=["hp", "mp", "exp", "mesos", "level", "inventory"], help="calibrate just these")
    sp.set_defaults(fn=cmd_calibrate)

    sp = sub.add_parser("snapshot", help="save screenshot, overlay and crops")
    frame_args(sp)
    sp.set_defaults(fn=cmd_snapshot)

    sub.add_parser("watch", help="print live readings").set_defaults(fn=cmd_watch)

    for name, fn in (("run", cmd_run), ("replay", cmd_replay)):
        sp = sub.add_parser(name, help="track a live session" if name == "run" else "track a recording")
        if name == "replay":
            sp.add_argument("video")
            sp.add_argument("--crop", action="store_true", help="apply capture.region to the video frames")
        sp.add_argument("--out", help="session log path (default: sessions/<time>_<monster>.jsonl)")
        sp.add_argument("--seconds", type=float, help="stop after this many seconds")
        sp.set_defaults(fn=fn)

    for name, fn in (("summarize", cmd_summarize), ("export", cmd_export)):
        sp = sub.add_parser(name)
        sp.add_argument("session")
        if name == "summarize":
            sp.add_argument("--json", action="store_true")
        sp.set_defaults(fn=fn)

    sp = sub.add_parser("snap", help="before/after snapshot of EXP, mesos and inventory")
    sp.add_argument("which", choices=["start", "end"])
    frame_args(sp)
    sp.set_defaults(fn=cmd_snap)

    sp = sub.add_parser("compare", help="compare the latest start and end snapshots")
    sp.add_argument("--start", help="start snapshot folder (default: latest start-*)")
    sp.add_argument("--end", help="end snapshot folder (default: latest end-*)")
    sp.add_argument("--minutes", type=float, help="grinding time, if you paused between snapshots")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_compare)

    sp = sub.add_parser("reread", help="read saved snapshots again from their screenshots")
    sp.add_argument("folders", nargs="*", help="snapshot folders (default: the latest start and end)")
    sp.set_defaults(fn=cmd_reread)

    sub.add_parser("items", help="list known item icons").set_defaults(fn=cmd_items)

    sp = sub.add_parser("review", help="review a session in your browser: fix misread slots, names, prices")
    sp.add_argument("session", nargs="?", help="end snapshot folder name (default: the latest session)")
    sp.add_argument("--port", type=int, default=0)
    sp.add_argument("--no-browser", action="store_true")
    sp.set_defaults(fn=cmd_review)

    sp = sub.add_parser("itemdb", help="download item names and icons from maplestory.io")
    sp.add_argument("--update", action="store_true", help="download again")
    sp.set_defaults(fn=cmd_itemdb)

    sp = sub.add_parser("identify", help="name catalog items by matching their icons with the item data")
    sp.add_argument("--all", action="store_true", help="also redo items named automatically before")
    sp.add_argument("--frame-h", type=int, help="game window height in pixels (default 1080)")
    sp.set_defaults(fn=cmd_identify)
    sub.add_parser("windows", help="list window titles (to set capture.window_title)").set_defaults(fn=cmd_windows)
    sub.add_parser("test-capture", help="grab the game window once and save it").set_defaults(fn=cmd_test_capture)
    sub.add_parser("gui", help="small always-on-top control window").set_defaults(fn=cmd_gui)

    sp = sub.add_parser("teach-digits", help="check the stack numbers it reads and correct any it got wrong")
    frame_args(sp)
    sp.add_argument("--yes", action="store_true", help="accept what was read without asking")
    sp.add_argument("--ask", action="store_true", help="show the picture even with --image")
    sp.set_defaults(fn=cmd_teach_digits)

    sp = sub.add_parser("label", help="name and price an item id")
    sp.add_argument("item")
    sp.add_argument("--name")
    sp.add_argument("--price", type=float, help="your price, mesos each (the NPC price is kept)")
    sp.add_argument("--npc-price", action="store_true", help="go back to the NPC sell price")
    sp.set_defaults(fn=cmd_label)

    a = p.parse_args(argv)
    cfg = Config.load(a.config)
    a.fn(cfg, a)


if __name__ == "__main__":
    sys.exit(main())
