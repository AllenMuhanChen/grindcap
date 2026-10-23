"""Sessions: a start snapshot plus the end snapshot after it, with a name, a map and a saved flag.

Snapshots live in <snapshot_dir>/start-*/ and end-*/. Each end snapshot is paired with the latest start
snapshot taken before it; the session's id is the end folder's name. What you change about a session
(name, map, saved) is kept in <snapshot_dir>/sessions.json. The map is read from the minimap when a
snapshot is taken (see mapname.py); the name defaults to "<map> · <start time> · <minutes> min".
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path


def _meta_path(root: Path) -> Path:
    return Path(root) / "sessions.json"


def load_meta(root) -> dict:
    p = _meta_path(root)
    return json.loads(p.read_text()) if p.exists() else {}


def save_meta(root, meta: dict):
    Path(root).mkdir(parents=True, exist_ok=True)
    _meta_path(root).write_text(json.dumps(meta, indent=2))


def _info(p: Path) -> dict | None:
    try:
        d = json.loads((p / "snapshot.json").read_text())
    except Exception:
        return None
    return {"time": d.get("time", 0), "map": d.get("map")}


def running(root) -> dict | None:
    """The start snapshot still waiting for its end snapshot (newer than every end), or None."""
    root = Path(root)
    starts = [(i["time"], p, i) for p in root.glob("start-*") if (i := _info(p))]
    if not starts:
        return None
    t, p, i = max(starts, key=lambda x: x[0])
    ends = [i2["time"] for q in root.glob("end-*") if (i2 := _info(q))]
    if ends and max(ends) >= t:
        return None
    return {"folder": str(p), "time": t, "map": (i.get("map") or {}).get("name")}


def default_name(map_name: str | None, start_time: float, minutes: float) -> str:
    when = datetime.fromtimestamp(start_time).strftime("%b %d %H:%M") if start_time else "?"
    return f"{map_name or 'Unknown map'} · {when} · {minutes:.0f} min"


def list_sessions(root) -> list[dict]:
    """Every session, newest first."""
    root = Path(root)
    starts = sorted(((i["time"], p, i) for p in root.glob("start-*") if (i := _info(p))), key=lambda x: x[0])
    meta = load_meta(root)
    out = []
    for p in root.glob("end-*"):
        e = _info(p)
        if e is None:
            continue
        before = [(t, sp, si) for t, sp, si in starts if t <= e["time"]]
        if not before:
            continue
        st, sp, si = before[-1]
        m = meta.get(p.name, {})
        read = (si.get("map") or e.get("map") or {}).get("name")
        map_name = m.get("map") or read
        minutes = (e["time"] - st) / 60
        out.append({
            "id": p.name, "start": str(sp), "end": str(p), "time": e["time"], "start_time": st,
            "minutes": round(minutes, 1), "map": map_name, "map_read": read,
            "map_changed": bool(si.get("map") and e.get("map") and si["map"].get("name") != e["map"].get("name")),
            "name": m.get("name") or default_name(map_name, st, minutes), "custom_name": m.get("name"),
            "saved": bool(m.get("saved")),
            "label": m.get("name") or default_name(map_name, st, minutes),
        })
    return sorted(out, key=lambda s: -s["time"])


def update(root, sid: str, **fields):
    """Change a session's name, map or saved flag. An empty name or map goes back to the default."""
    meta = load_meta(root)
    m = meta.setdefault(sid, {})
    for k in ("name", "map", "saved"):
        if k in fields:
            v = fields[k]
            if isinstance(v, str):
                v = v.strip()
            if v in (None, "", False):
                m.pop(k, None)
            else:
                m[k] = v
    if not m:
        meta.pop(sid, None)
    save_meta(root, meta)


def delete(root, sid: str) -> list[str]:
    """Delete a session's snapshots: its end snapshot, and its start snapshot unless another session
    still uses it. Returns the folders removed."""
    root = Path(root)
    ss = list_sessions(root)
    s = next((x for x in ss if x["id"] == sid), None)
    if s is None:
        raise KeyError(f"No session {sid}")
    removed = [s["end"]]
    if not any(x["start"] == s["start"] for x in ss if x["id"] != sid):
        removed.append(s["start"])
    for f in removed:
        shutil.rmtree(f, ignore_errors=True)
    meta = load_meta(root)
    meta.pop(sid, None)
    save_meta(root, meta)
    return removed
