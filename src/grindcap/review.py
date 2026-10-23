"""Review a grind session (start + end snapshot) and fix what was read wrong.

Shows only items whose count changed (plus anything you already fixed). For each one you can:
  - rename it or set your own price (kept in the catalog, so it applies to every session),
  - pick its name from the game's item list (e.g. which scroll it is; icons several items share),
  - open its slots in the start and end screenshots and, per slot, fix the count, say it's really a
    different item (a cursor or menu covered it), or ignore it.
EXP, level and mesos of each snapshot can be corrected too. Slot and status corrections are saved
next to each snapshot (fixes.json), so they survive `grindcap reread`; `compare` uses them.

`serve()` runs a small local web page (only reachable from this computer) for doing all this.
"""
from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .inventory import Catalog
from .snapshot import apply_fixes, compare, load_snapshot, save_fixes


# ---------------------------------------------------------------- sessions

def list_sessions(root: str | Path) -> list[dict]:
    """Every end snapshot, paired with the latest start snapshot taken before it. Newest first."""
    root = Path(root)

    def when(p):
        try:
            return json.loads((p / "snapshot.json").read_text())["time"]
        except Exception:
            return 0

    starts = sorted((when(p), p) for p in root.glob("start-*") if (p / "snapshot.json").exists())
    out = []
    for p in root.glob("end-*"):
        if not (p / "snapshot.json").exists():
            continue
        t = when(p)
        before = [s for ts, s in starts if ts <= t]
        if before:
            out.append({"id": p.name, "start": str(before[-1]), "end": str(p), "time": t,
                        "label": f"{before[-1].name.replace('start-', '')} to {p.name.replace('end-', '')}"})
    return sorted(out, key=lambda s: -s["time"])


# ---------------------------------------------------------------- the data the page shows

def _snap_slots(snap, iid):
    fx = (snap.get("fixes") or {}).get("slots") or {}
    out = []
    for sl in snap.get("slots", []):
        f = fx.get(sl["ref"], {})
        eff = None if f.get("ignore") else f.get("item", sl["item"])
        if sl["item"] == iid or eff == iid:
            out.append({"ref": sl["ref"], "read_item": sl["item"], "read_qty": sl["qty"],
                        "item": eff, "qty": f.get("qty", sl["qty"]), "ignored": bool(f.get("ignore")),
                        "fixed": bool(f)})
    return out


def review_data(start_dir, end_dir, catalog: Catalog, itemdb=None) -> dict:
    s, e = load_snapshot(start_dir), load_snapshot(end_dir)
    r = compare(s, e, catalog)
    ids = [it["id"] for it in r["items"]]
    for snap in (s, e):   # items you touched stay listed even if they no longer change
        for ref, f in ((snap.get("fixes") or {}).get("slots") or {}).items():
            orig = next((sl["item"] for sl in snap.get("slots", []) if sl["ref"] == ref), None)
            for iid in (orig, f.get("item")):
                if iid and iid != "?" and iid not in ids:
                    ids.append(iid)
    deleted = set((s.get("fixes") or {}).get("deleted", [])) | set((e.get("fixes") or {}).get("deleted", []))
    ids += [i for i in sorted(deleted) if i not in ids]
    ids = [i for i in ids if i in catalog.items]        # purged items are gone
    rows = {it["id"]: it for it in r["items"]}
    es, ee = apply_fixes(s), apply_fixes(e)
    items = []
    for iid in ids:
        info = catalog.items.get(iid, {})
        base = rows.get(iid) or {"before": es["items"].get(iid, 0), "after": ee["items"].get(iid, 0),
                                 "change": 0, "per_hr": 0, "value": 0}
        cands = []
        if itemdb is not None and not info.get("manual"):
            cands = [{"db_id": c, "name": itemdb.items[c]["name"]}
                     for c in info.get("candidates") or [] if c in itemdb.items]
        items.append({
            "id": iid, "name": info.get("name") or "", "price": catalog.price(iid),
            "custom_price": info.get("price"), "npc_price": info.get("npc_price"),
            "auto_named": bool(info.get("db")) and not (info.get("db") or {}).get("manual")
                          and not info.get("name_manual"),
            "db_match": {k: (info.get("db") or {}).get(k) for k in ("score", "ratio", "runner_up")},
            "candidates": cands,
            "before": base["before"], "after": base["after"], "change": base["change"],
            "per_hr": base.get("per_hr"), "value": base.get("value"),
            "slots": {"start": _snap_slots(s, iid), "end": _snap_slots(e, iid)},
        })
        items[-1]["deleted"] = iid in deleted
        if iid in deleted:   # what was read, so you can see what you deleted
            raw = [apply_fixes({**x, "fixes": {**(x.get("fixes") or {}), "deleted": []}}) for x in (s, e)]
            items[-1]["read_before"], items[-1]["read_after"] = (r_["items"].get(iid, 0) for r_ in raw)
    # slots a tooltip covered and that you haven't said what they are yet
    covered = {name: [x for x in _snap_slots(snap, "?") if x["item"] in ("?", None) and not x["ignored"]]
               for name, snap in (("start", s), ("end", e))}
    status = {}
    for name, snap in (("start", s), ("end", e)):
        fx = (snap.get("fixes") or {}).get("status") or {}
        status[name] = {k: {"read": snap.get(k), "fixed": fx.get(k)} for k in ("level", "exp", "mesos")}
        status[name]["when"] = snap.get("when")
    summary = {k: r[k] for k in ("minutes", "exp", "exp_per_hr", "levels", "mesos", "mesos_per_hr",
                                 "items_gained_value", "items_used_value", "net_mesos_incl_items",
                                 "net_per_hr")}
    return {"summary": summary, "status": status, "items": items, "covered": covered,
            "catalog": sorted(([iid, it.get("name") or iid] for iid, it in catalog.items.items()),
                              key=lambda x: x[1].lower())}


# ---------------------------------------------------------------- edits

def apply_edit(start_dir, end_dir, catalog: Catalog, itemdb, edit: dict) -> None:
    op = edit.get("op")
    folders = {"start": Path(start_dir), "end": Path(end_dir)}
    if op in ("slot", "slot_db", "reset", "status"):
        folder = folders[edit["snap"]]
        snap = load_snapshot(folder)
        fixes = snap.get("fixes") or {}
        if op == "status":
            st = fixes.setdefault("status", {})
            v = edit.get("value")
            st[edit["field"]] = None if v in (None, "") else int(v)
            if st[edit["field"]] is None:
                del st[edit["field"]]
        else:
            ref = edit["ref"]
            sl = next((x for x in snap.get("slots", []) if x["ref"] == ref), None)
            if sl is None:
                raise KeyError(f"No slot {ref} in {folder.name}")
            slots = fixes.setdefault("slots", {})
            if op == "reset":
                slots.pop(ref, None)
            else:
                f = dict(slots.get(ref, {}))
                if op == "slot_db":
                    f["item"] = item_for_db(catalog, itemdb, int(edit["db_id"]))
                if "item" in edit:
                    f["item"] = edit["item"]
                if edit.get("qty") not in (None, ""):
                    f["qty"] = int(edit["qty"])
                if "ignore" in edit:
                    f["ignore"] = bool(edit["ignore"])
                # drop parts that just repeat what was read
                if f.get("item") == sl["item"]:
                    f.pop("item")
                if f.get("qty") == sl["qty"]:
                    f.pop("qty")
                if not f.get("ignore"):
                    f.pop("ignore", None)
                if f:
                    slots[ref] = f
                else:
                    slots.pop(ref, None)
        save_fixes(folder, fixes)
    elif op == "ignore_item":
        # Delete a misread item from this session (or restore it). Recorded per snapshot, so it works
        # for every snapshot, including ones saved before slots were recorded.
        iid, on = edit["id"], bool(edit.get("ignore", True))
        for folder in folders.values():
            fixes = load_snapshot(folder).get("fixes") or {}
            deleted = [x for x in fixes.get("deleted", []) if x != iid] + ([iid] if on else [])
            fixes["deleted"] = deleted
            if not deleted:
                fixes.pop("deleted")
            save_fixes(folder, fixes)
    elif op in ("purge", "purge_deleted"):
        # Remove items from the catalog for good (their icons too). Snapshots that still mention
        # them simply don't count them any more.
        if op == "purge":
            ids = [edit["id"]]
        else:
            ids = sorted({x for f in folders.values() for x in (load_snapshot(f).get("fixes") or {}).get("deleted", [])})
        for iid in ids:
            catalog.remove(iid)
            for folder in folders.values():
                fixes = load_snapshot(folder).get("fixes") or {}
                if iid in fixes.get("deleted", []):
                    fixes["deleted"].remove(iid)
                    if not fixes["deleted"]:
                        fixes.pop("deleted")
                    save_fixes(folder, fixes)
    elif op == "item":
        iid = edit["id"]
        it = catalog.items[iid]
        if "name" in edit:
            name = (edit["name"] or "").strip() or None
            if name != it.get("name"):
                it["name"] = name
                it["name_manual"] = bool(name)   # automatic naming never overwrites it
        if "price" in edit:
            p = edit["price"]
            it["price"] = None if p in (None, "") else float(p)   # None = back to the NPC price
        catalog.save()
    elif op == "item_db":
        # The whole item is this database item (e.g. you picked which scroll it is).
        db_id = int(edit["db_id"])
        it = catalog.items[edit["id"]]
        other = catalog.by_db(db_id)
        if other and other != edit["id"]:
            raise ValueError(f"{itemdb.items[db_id]['name']} is already {other}; assign slots to it instead.")
        it["name"] = itemdb.items[db_id]["name"]
        it["db"] = {"id": db_id, "manual": True}
        it["npc_price"] = itemdb.price(db_id)
        catalog.save()
    else:
        raise ValueError(f"Unknown edit {op!r}")


def item_for_db(catalog: Catalog, itemdb, db_id: int) -> str:
    """Catalog id for a database item, creating it (named, NPC-priced) if it isn't in the catalog yet."""
    iid = catalog.by_db(db_id)
    if iid:
        return iid
    return catalog.add_named(itemdb.items[db_id]["name"], db_id, itemdb.price(db_id), itemdb.icon_path(db_id))


# ---------------------------------------------------------------- pictures

def slot_crop_png(folder, ref: str, scale: int = 3) -> bytes | None:
    import cv2

    snap = load_snapshot(folder)
    sl = next((x for x in snap.get("slots", []) if x["ref"] == ref), None)
    if sl is None or not sl.get("box"):
        return None
    page = ref.split(":")[0]
    img = cv2.imread(str(Path(folder) / f"{page}.png"))
    if img is None:
        return None
    x, y, w, h = sl["box"]
    m = 6   # a little context around the slot
    crop = img[max(0, y - m):y + h + m, max(0, x - m):x + w + m]
    crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    ok, buf = cv2.imencode(".png", crop)
    return buf.tobytes() if ok else None


# ---------------------------------------------------------------- local web page

def serve(cfg, session_id: str | None = None, open_browser: bool = True, port: int = 0):
    """Start the review page on http://127.0.0.1:<port>/ in a background thread; returns the server."""
    from .snapshot import open_itemdb

    root = Path(cfg["inventory"]["snapshot_dir"])
    cat_dir = cfg["inventory"]["catalog_dir"]
    itemdb = open_itemdb(cfg, download=False)
    page = (Path(__file__).parent / "data" / "review.html").read_text(encoding="utf-8")
    lock = threading.Lock()

    def session(sid):
        ss = list_sessions(root)
        if not ss:
            raise LookupError("No sessions yet: take a start and an end snapshot first.")
        return next((s for s in ss if s["id"] == sid), ss[0])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body: bytes, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj).encode())

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path == "/":
                    return self._send(200, page.encode(), "text/html; charset=utf-8")
                if u.path == "/api/sessions":
                    return self._json({"sessions": list_sessions(root), "selected": session_id})
                if u.path == "/api/data":
                    s = session(q.get("session"))
                    with lock:
                        d = review_data(s["start"], s["end"], Catalog(cat_dir), itemdb)
                    d["session"] = s
                    d["has_itemdb"] = itemdb is not None
                    return self._json(d)
                if u.path == "/api/search":
                    hits = itemdb.search(q.get("q", "")) if itemdb else []
                    return self._json([{"db_id": i, "name": n} for i, n in hits])
                if u.path == "/crop":
                    s = session(q.get("session"))
                    png = slot_crop_png(s[q["snap"]], q["ref"])
                    return self._send(200, png, "image/png") if png else self._send(404, b"")
                if u.path == "/icon":
                    p = Catalog(cat_dir).icons_dir / f"{q['id']}.png"
                    return self._send(200, p.read_bytes(), "image/png") if p.exists() else self._send(404, b"")
                if u.path == "/dbicon" and itemdb:
                    p = itemdb.icon_path(int(q["id"]))
                    return self._send(200, p.read_bytes(), "image/png") if p.exists() else self._send(404, b"")
                self._send(404, b"")
            except Exception as e:
                self._json({"error": str(e)}, 500)

        def do_POST(self):
            u = urlparse(self.path)
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                if u.path == "/api/edit":
                    s = session(body.get("session"))
                    with lock:
                        apply_edit(s["start"], s["end"], Catalog(cat_dir), itemdb, body)
                    return self._json({"ok": True})
                self._send(404, b"")
            except Exception as e:
                self._json({"error": str(e)}, 400)

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/" + (f"?session={session_id}" if session_id else "")
    httpd.url = url
    if open_browser:
        webbrowser.open(url)
    return httpd
