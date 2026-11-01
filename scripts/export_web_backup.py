"""Turn the sessions saved by grindcap-gui (the Python app) into a backup file the browser version can
load with "Restore from backup".

  python scripts/export_web_backup.py --character ImmovableObj --job Spearman

Writes grindcap-backup-from-gui.json in the repo root (or --out). Per session it carries over: start and
end snapshots with your corrections applied (fixes.json: status, slot items/counts, deleted items),
items named by their item-data id (so prices come from the same place as in the browser), the session
name and map from sessions.json, pauses, live EXP readings, quick slot potion readings and their names,
and the captured inventory pages as pictures (--no-pictures leaves them out; the file is much smaller).
Items you named that have no item-data id keep your catalog name and price.

It prints each session's net mesos/hr and EXP/hr as the Python app works them out, so you can check
them against the browser after restoring. Nothing in the Python app's folders is changed.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _abs(p) -> Path:
    p = Path(p)
    return p if p.is_absolute() else ROOT / p


def item_key(iid: str, catalog) -> tuple[object, str, object] | None:
    """(browser item id, name, own price) for a catalog id; None if it is no longer in the catalog."""
    it = catalog.items.get(iid)
    if it is None:
        return None
    db = (it.get("db") or {}).get("id")
    name = it.get("name") or iid
    if db is not None:
        try:
            return int(db), name, None
        except (TypeError, ValueError):
            pass
    return f"gui:{iid}", name, catalog.price(iid)


def web_snapshot(snap: dict, folder: Path, catalog, prices: dict, pictures: bool) -> dict:
    """A Python snapshot (fixes applied) in the browser's snapshot shape."""
    from grindcap.snapshot import apply_fixes

    fixed = apply_fixes(snap)
    fx = snap.get("fixes") or {}
    sf, deleted = fx.get("slots") or {}, set(fx.get("deleted") or [])
    tabs: dict[str, list] = {}
    for sl in snap.get("slots") or []:
        f = sf.get(sl["ref"], {})
        if f.get("ignore"):
            continue
        iid, n = f.get("item", sl["item"]), int(f.get("qty", sl["qty"]))
        if not iid or iid == "?" or iid in deleted:
            continue
        k = item_key(iid, catalog)
        if k is None:                       # purged from the catalog: the Python app doesn't count it either
            continue
        wid, name, own = k
        if own is not None:
            prices[wid] = own
        tabs.setdefault(sl.get("tab") or "Inventory", [[]])[0].append(
            {"id": wid, "name": name, "qty": n, "ref": sl["ref"], "look": None, "how": "from grindcap-gui"})
    if not tabs and fixed.get("items"):     # very old snapshots without per-slot data
        row = []
        for iid, n in fixed["items"].items():
            k = item_key(iid, catalog)
            if k:
                row.append({"id": k[0], "name": k[1], "qty": int(n), "ref": iid, "look": None, "how": "from grindcap-gui"})
                if k[2] is not None:
                    prices[k[0]] = k[2]
        tabs["Inventory"] = [row]
    items: dict = {}
    for rows in tabs.values():
        for s in rows[0]:
            e = items.setdefault(s["id"], {"qty": 0, "name": s["name"]})
            e["qty"] += s["qty"]
    out = {
        "time": int(round(snap["time"] * 1000)), "when": snap.get("when"),
        "level": fixed.get("level"), "exp": fixed.get("exp"), "exp_pct": fixed.get("exp_pct"),
        "exp_checked": fixed.get("exp_checked"), "mesos": fixed.get("mesos"), "mesos_checked": fixed.get("mesos_checked"),
        "map": snap.get("map"), "tabs": tabs, "items": items, "looks": {}, "from_gui": folder.name,
    }
    if pictures:
        out["pictures"] = page_pictures(folder, snap)
    return out


def page_pictures(folder: Path, snap: dict) -> list[dict]:
    """The saved inventory pages, cropped to the inventory window, as JPEG data URLs."""
    import cv2

    boxes = [s["box"] for s in snap.get("slots") or [] if s.get("box")]
    out = []
    for i, p in enumerate(sorted(folder.glob("*_[0-9][0-9].png")), 1):
        img = cv2.imread(str(p))
        if img is None:
            continue
        if boxes:
            x0 = min(b[0] for b in boxes); y0 = min(b[1] for b in boxes)
            x1 = max(b[0] + b[2] for b in boxes); y1 = max(b[1] + b[3] for b in boxes)
            pw = boxes[0][2]
            img = img[max(0, int(y0 - 1.2 * pw)):int(y1 + 2.2 * pw), max(0, int(x0 - 0.5 * pw)):int(x1 + 1.5 * pw)]
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            out.append({"tab": p.stem.rsplit("_", 1)[0], "n": i, "img": "data:image/jpeg;base64," + base64.b64encode(buf).decode()})
    return out


def main() -> int:
    from grindcap.config import Config
    from grindcap.inventory import Catalog
    from grindcap.quickslot import load_names
    from grindcap.sessions import list_sessions, load_pauses
    from grindcap.snapshot import compare, load_live, load_snapshot

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--character", help="character name to put on every session (e.g. ImmovableObj)")
    ap.add_argument("--job", help="class to put on every session (e.g. Spearman)")
    ap.add_argument("--out", default=str(ROOT / "grindcap-backup-from-gui.json"))
    ap.add_argument("--snapshots", help="snapshot folder (default: config inventory.snapshot_dir)")
    ap.add_argument("--catalog", help="catalog folder (default: config inventory.catalog_dir)")
    ap.add_argument("--no-pictures", action="store_true", help="leave the inventory page pictures out")
    args = ap.parse_args()

    cfg = Config.load(ROOT / "config.yaml")
    root = _abs(args.snapshots or cfg["inventory"]["snapshot_dir"])
    catalog = Catalog(_abs(args.catalog or cfg["inventory"]["catalog_dir"]))
    sessions = list_sessions(root)
    if not sessions:
        print(f"No finished sessions in {root}.")
        return 1
    character = {"name": args.character, "job": args.job} if args.character else None
    prices: dict = {}
    out = []
    for s in sessions:
        sp, ep = Path(s["start"]), Path(s["end"])
        try:
            a, b = load_snapshot(sp), load_snapshot(ep)
        except Exception as e:  # a broken folder: skip it, say so
            print(f"  skipped {s['id']}: {e}")
            continue
        pauses = load_pauses(sp)
        a["pauses"] = pauses
        r = compare(a, b, catalog)
        start = web_snapshot(a, sp, catalog, prices, not args.no_pictures)
        end = web_snapshot(b, ep, catalog, prices, not args.no_pictures)
        if s.get("map"):
            for w in (start, end):
                w["map"] = {**(w.get("map") or {}), "name": s["map"]}
        live = [{"t": start["time"], "level": start["level"], "exp": start["exp"], "pct": start["exp_pct"]}]
        pots = []
        for row in load_live(sp):
            if row.get("time", 0) > b["time"] + 1:
                continue
            if row.get("checked") and row.get("exp") is not None and row.get("level") is not None:
                live.append({"t": int(row["time"] * 1000), "level": row["level"], "exp": row["exp"], "pct": None})
            if row.get("potions"):
                pots.append({"time": row["time"], "potions": row["potions"]})
        live.append({"t": end["time"], "level": end["level"], "exp": end["exp"], "pct": end["exp_pct"]})
        rec = {
            "id": start["time"], "name": s["name"], "start": start, "end": end,
            "fixes": {"looks": {}, "qty": {}, "status": {"start": {}, "end": {}}},
            "live": {"rows": live, "fails": 0},
            "pauses": [[int(p0 * 1000), int(p1 * 1000) if p1 is not None else end["time"]] for p0, p1 in pauses],
            "potions": pots, "qsNames": load_names(sp), "character": character,
            "result": None, "saved": end["time"], "from_gui": s["id"],
        }
        out.append(rec)
        print(f"  {s['name']}: net {r['net_per_hr'] or 0:,.0f}/hr, EXP {r['exp_per_hr'] or 0:,.0f}/hr, {r['minutes']} min")
    chars = [character] if character else []
    backup = {"kind": "grindcap-backup", "version": 1, "made_by": "export_web_backup.py", "sessions": out,
              "kv": {"characters": chars, "char": character, "prices": {str(k): v for k, v in prices.items()}}}
    Path(args.out).write_text(json.dumps(backup))
    mb = Path(args.out).stat().st_size / 1e6
    print(f"{len(out)} sessions -> {args.out} ({mb:.1f} MB). In the browser: Your data > Restore from backup.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
