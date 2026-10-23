"""Turn a stream of readings into game events.

Each frame gives (maybe) a value for hp, mp, exp and mesos. A value only counts once it has held
steady for `settle_frames` frames, so bar animations and one-frame OCR misreads are ignored.
Changes between accepted values become events:

  hp down            -> touch        (a monster hit you; data: dmg)
  hp up, small       -> hp_regen
  hp up, after FA    -> fa_heal      (gain within 1.5 s of a Final Attack cast)
  hp up, bigger      -> hp_potion
  mp down = a cost   -> cast         (data: skill)
  mp down, no match  -> mp_spend
  mp up, small       -> mp_regen
  mp up, bigger      -> mp_potion
  exp up             -> kill         (data: exp, n = kills, split using monster_exp)
  exp wraps around   -> level_up     (then the kill that caused it)
  mesos up           -> meso         (data: amount)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations_with_replacement

from .gamedata import exp_to_next


@dataclass
class Event:
    t: float
    kind: str
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"t": round(self.t, 3), "kind": self.kind, **self.data}


class Stabilizer:
    """Accept a new value only after it is seen `n` frames in a row."""

    def __init__(self, n: int):
        self.n = max(1, n)
        self.accepted = None
        self._cand = None
        self._count = 0

    def push(self, v):
        """Returns (old, new) when a new value is accepted, else None."""
        if v is None:
            return None
        if v == self.accepted:
            self._cand, self._count = None, 0
            return None
        if v == self._cand:
            self._count += 1
        else:
            self._cand, self._count = v, 1
        if self._count >= self.n:
            old, self.accepted = self.accepted, v
            self._cand, self._count = None, 0
            return (old, v)
        return None


class EventDetector:
    def __init__(self, cfg):
        d = cfg["detection"]
        self.d = d
        self.skills: dict[str, float] = dict(cfg["character"]["skills"] or {})
        self.level = int(cfg["character"]["level"])
        self.monster_exp = cfg["session"].get("monster_exp")
        self.exp_mode = cfg["readers"]["exp"].get("mode", "text")
        n = d["settle_frames"]
        self.stab = {k: Stabilizer(n) for k in ("hp", "mp", "exp", "mesos")}
        self.last_fa_t = -1e9

    # --- MP: which combination of skill costs explains this drop? ---
    def match_casts(self, drop: float) -> list[str] | None:
        tol = self.d["mp_tol"]
        names = list(self.skills)
        for k in (1, 2, 3):
            for combo in combinations_with_replacement(names, k):
                if abs(sum(self.skills[c] for c in combo) - drop) <= tol:
                    return list(combo)
        return None

    def _exp_points(self, v: float) -> float:
        """Bar mode reads a fraction of the level; convert it to EXP points."""
        if self.exp_mode == "bar":
            need = exp_to_next(self.level) or 0
            return v * need
        return v

    def process(self, t: float, values: dict) -> list[Event]:
        ev: list[Event] = []
        for key in ("mp", "hp", "exp", "mesos"):  # mp first so FA heals can be attributed
            if key not in values:
                continue
            ch = self.stab[key].push(values[key])
            if not ch or ch[0] is None:
                continue
            old, new = ch
            getattr(self, f"_on_{key}")(t, old, new, ev)
        return ev

    def _on_hp(self, t, old, new, ev):
        delta = new - old
        if abs(delta) < self.d["hp_noise"]:
            return
        if delta < 0:
            ev.append(Event(t, "touch", {"dmg": -delta, "hp": new}))
        elif t - self.last_fa_t <= 1.5:
            ev.append(Event(t, "fa_heal", {"amount": delta}))
        elif delta <= self.d["hp_regen_max"]:
            ev.append(Event(t, "hp_regen", {"amount": delta}))
        else:
            ev.append(Event(t, "hp_potion", {"amount": delta}))

    def _on_mp(self, t, old, new, ev):
        delta = new - old
        if delta < 0:
            casts = self.match_casts(-delta)
            if casts:
                for c in casts:
                    ev.append(Event(t, "cast", {"skill": c, "mp": self.skills[c]}))
                    if "final attack" in c.lower():
                        self.last_fa_t = t
            else:
                ev.append(Event(t, "mp_spend", {"amount": -delta}))
        elif delta <= self.d["mp_regen_max"]:
            ev.append(Event(t, "mp_regen", {"amount": delta}))
        else:
            ev.append(Event(t, "mp_potion", {"amount": delta}))

    def _on_exp(self, t, old, new, ev):
        o, n = self._exp_points(old), self._exp_points(new)
        if n < o:  # wrapped past a level
            need = exp_to_next(self.level) or o
            gained = (need - o) + n
            self.level += 1
            ev.append(Event(t, "level_up", {"level": self.level}))
        else:
            gained = n - o
        if gained <= 0:
            return
        kills = 1
        if self.monster_exp:
            kills = max(1, round(gained / float(self.monster_exp)))
            if kills > self.d["max_kills_per_step"]:
                ev.append(Event(t, "exp_jump", {"exp": round(gained, 1), "note": "ignored, looks like a misread"}))
                return
        ev.append(Event(t, "kill", {"exp": round(gained, 1), "n": kills}))

    def _on_mesos(self, t, old, new, ev):
        delta = new - old
        if delta > 0:
            ev.append(Event(t, "meso", {"amount": delta}))
        elif delta < 0:
            ev.append(Event(t, "meso_spend", {"amount": -delta}))
