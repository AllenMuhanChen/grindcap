"""Run a tracking session, log events to JSONL, and summarise them."""
from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from .events import Event, EventDetector
from .readers import build_readers


def read_values(readers: dict, frame) -> dict:
    """Run every reader on a frame. Returns {name: value} for readers that saw a number."""
    out = {}
    for name, r in readers.items():
        rd = r.read(frame)
        if rd.value is not None:
            out[name] = rd.value
    return out


class Tracker:
    def __init__(self, cfg, source, out_path: Path | None = None,
                 on_event: Callable[[Event], None] | None = None):
        self.cfg = cfg
        self.source = source
        self.readers = build_readers(cfg)
        self.detector = EventDetector(cfg)
        self.events: list[Event] = []
        self.out_path = out_path
        self.on_event = on_event

    def run(self, max_seconds: float | None = None) -> list[Event]:
        fh = None
        if self.out_path:
            self.out_path.parent.mkdir(parents=True, exist_ok=True)
            fh = self.out_path.open("w")
            fh.write(json.dumps({"kind": "session", "started": datetime.now().isoformat(timespec="seconds"),
                                 "monster": self.cfg["session"]["monster"],
                                 "monster_exp": self.cfg["session"].get("monster_exp"),
                                 "level": self.cfg["character"]["level"],
                                 "skills": self.cfg["character"]["skills"]}) + "\n")
        try:
            for t, frame in self.source.frames():
                if max_seconds is not None and t > max_seconds:
                    break
                for e in self.detector.process(t, read_values(self.readers, frame)):
                    self.events.append(e)
                    if fh:
                        fh.write(json.dumps(e.to_dict()) + "\n")
                        fh.flush()
                    if self.on_event:
                        self.on_event(e)
        except KeyboardInterrupt:
            pass
        finally:
            if fh:
                fh.close()
        return self.events


def default_session_path(cfg) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = str(cfg["session"]["monster"]).replace(" ", "_")
    return Path(cfg["session"]["out_dir"]) / f"{stamp}_{name}.jsonl"


def load_events(path: str | Path) -> tuple[dict, list[dict]]:
    header, events = {}, []
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        if d.get("kind") == "session":
            header = d
        else:
            events.append(d)
    return header, events


def summarize(events: Iterable[dict | Event]) -> dict:
    ev = [e.to_dict() if isinstance(e, Event) else e for e in events]
    ev.sort(key=lambda e: e["t"])
    kinds = Counter(e["kind"] for e in ev)
    kill_ev = [e for e in ev if e["kind"] == "kill"]
    kills = sum(e.get("n", 1) for e in kill_ev)
    dur = (ev[-1]["t"] - ev[0]["t"]) if len(ev) > 1 else 0.0
    hours = dur / 3600 if dur else 0.0

    # Split the session into fights: everything after one kill up to and including the next.
    gaps, fights, casts_per, touches_per = [], [], [], []
    for prev, cur in zip(kill_ev, kill_ev[1:]):
        window = [e for e in ev if prev["t"] < e["t"] <= cur["t"]]
        casts = [e for e in window if e["kind"] == "cast"]
        n = cur.get("n", 1)
        casts_per.append(len(casts) / n)
        touches_per.append(sum(1 for e in window if e["kind"] == "touch") / n)
        if casts:
            first = casts[0]["t"]
            gaps.append(first - prev["t"])
            fights.append(cur["t"] - first)

    def mean(xs):
        return round(sum(xs) / len(xs), 2) if xs else None

    total = lambda kind, key: sum(e.get(key, 0) for e in ev if e["kind"] == kind)
    exp = total("kill", "exp")
    mesos = total("meso", "amount")
    touch_dmg = total("touch", "dmg")
    skills = Counter(e.get("skill") for e in ev if e["kind"] == "cast")
    return {
        "duration_s": round(dur, 1),
        "kills": kills,
        "exp": round(exp, 1),
        "exp_per_hr": round(exp / hours) if hours else None,
        "kills_per_hr": round(kills / hours, 1) if hours else None,
        "mesos_picked_up": mesos,
        "mesos_per_hr": round(mesos / hours) if hours else None,
        "mesos_per_kill": round(mesos / kills, 2) if kills else None,
        "touches": kinds["touch"],
        "touches_per_kill": round(kinds["touch"] / kills, 2) if kills else None,
        "avg_touch_dmg": round(touch_dmg / kinds["touch"], 1) if kinds["touch"] else None,
        "casts": dict(skills),
        "casts_per_kill": round(kinds["cast"] / kills, 2) if kills else None,
        "secs_between_kills": mean(gaps),      # from a kill to your first cast on the next monster
        "secs_fighting_per_kill": mean(fights),  # from that first cast to the kill
        "hp_potion_hp": total("hp_potion", "amount"),
        "mp_potion_mp": total("mp_potion", "amount"),
        "fa_heal_hp": total("fa_heal", "amount"),
        "level_ups": kinds["level_up"],
        "event_counts": dict(kinds),
        "fights_measured": len(fights),
    }


def ledger_export(header: dict, summary: dict) -> dict:
    """Values to paste into Grind Ledger's monster editor."""
    return {
        "monster": header.get("monster"),
        "touches_per_kill": summary["touches_per_kill"],
        "secs_between_kills": summary["secs_between_kills"],
        "mesos_dropped_per_kill": summary["mesos_per_kill"],
        "measured": {k: summary[k] for k in ("kills", "duration_s", "exp_per_hr", "mesos_per_hr",
                                             "casts_per_kill", "secs_fighting_per_kill", "avg_touch_dmg")},
    }


def format_summary(s: dict) -> str:
    rows = [
        ("Duration", f"{s['duration_s'] / 60:.1f} min"),
        ("Kills", s["kills"]),
        ("EXP/hr", s["exp_per_hr"]),
        ("Mesos/hr (floor mesos)", s["mesos_per_hr"]),
        ("Mesos per kill", s["mesos_per_kill"]),
        ("Touches per kill", s["touches_per_kill"]),
        ("Avg touch damage", s["avg_touch_dmg"]),
        ("Casts per kill", s["casts_per_kill"]),
        ("Secs between kills", s["secs_between_kills"]),
        ("Secs fighting per kill", s["secs_fighting_per_kill"]),
        ("HP from potions", s["hp_potion_hp"]),
        ("MP from potions", s["mp_potion_mp"]),
        ("HP from Final Attack", s["fa_heal_hp"]),
        ("Casts", ", ".join(f"{k} {v}" for k, v in s["casts"].items()) or "-"),
    ]
    w = max(len(r[0]) for r in rows)
    return "\n".join(f"{k.ljust(w)}  {'-' if v is None else v}" for k, v in rows)
