"""Configuration: where things are on screen, what your skills cost, and detection thresholds.

The config is a plain YAML file (default: config.yaml next to where you run grindcap).
`grindcap calibrate` writes the reader boxes for you; everything else you edit by hand.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG: dict[str, Any] = {
    "capture": {
        # mss monitor index: 1 is the primary monitor. 0 is all monitors stitched together.
        "monitor": 1,
        # Optional sub-rectangle of the monitor to grab: {left, top, width, height}.
        # Reader boxes are always relative to this area (or to the whole monitor if null).
        "region": None,
        # Frames per second to sample. 8 is enough to separate individual hits.
        "fps": 8,
        # Capture only the game window: any window whose title contains this text (Windows only).
        # Set to null to capture the whole monitor instead. `grindcap windows` lists window titles.
        "window_title": "MapleStory",
    },
    "character": {
        "level": 30,
        # MP cost of each skill you cast. An MP drop that matches a cost is counted as that cast.
        "skills": {"Power Strike": 4, "Final Attack": 8},
        # Only needed when HP/MP are read as bars (bars give a fraction, this turns it into points).
        "max_hp": None,
        "max_mp": None,
    },
    "readers": {
        # mode "text": OCR the numbers in the box (e.g. "312/450"). Needs Tesseract installed.
        # mode "bar":  measure how full a coloured bar is. No OCR needed.
        # box: [x, y, width, height] in pixels, relative to the capture area.
        "hp": {"mode": "text", "box": None},
        "mp": {"mode": "text", "box": None},
        "exp": {"mode": "text", "box": None},
        # Your meso total in the inventory window (keep the inventory open while grinding).
        "mesos": {"mode": "text", "box": None},
        # Optional: your level number, so before/after snapshots can tell how many levels you gained.
        "level": {"mode": "text", "box": None},
    },
    "inventory": {
        # Boxes [x, y, w, h] of the top-left and bottom-right *visible* slots of the inventory grid.
        "first_slot": None,
        "last_slot": None,
        "cols": 4,
        "rows": 6,
        # Where the stack number sits inside a slot, as fractions [x, y, w, h] of the slot.
        "qty_box": [0.0, 0.62, 0.75, 0.38],
        # A slot whose icon area varies less than this (grey-level std) is empty.
        "empty_std": 6.0,
        # Icons closer than this (mean absolute pixel difference) count as the same item.
        "match_threshold": 12.0,
        # Inventory tab names, in the order you capture them.
        "tabs": ["Equip", "Use", "Etc", "Setup"],
        # Item catalog (icons, names, prices) and snapshot folders.
        "catalog_dir": "data",
        "snapshot_dir": "snapshots",
        # Tabs not counted: nothing in them changes while grinding, and their icons (cash items,
        # cosmetics) aren't in the item data, so they only add misreads. The open tab is detected
        # from the highlighted tab button.
        "skip_tabs": ["Cash", "Deco"],
        # Finish a snapshot by itself this many seconds after the last new page, once every counted
        # tab has a page (0 = only when you press Finish).
        "auto_finish_after": 4,
        # Name new items by matching their icons with the game's data from maplestory.io
        # (region MCW = MapleStory Classic World). Downloaded once into <catalog_dir>/itemdb/.
        "itemdb": {"enabled": True, "region": "MCW", "version": "1", "min_ratio": 1.25},
    },
    "anchors": {
        # Patches of windows that never change, used to find the windows wherever they are on screen.
        # Set by `grindcap calibrate`; the images are saved in <catalog_dir>/anchors/.
        "inventory": None,
        "status": None,
        # How closely the screen must match the saved patch (0-1).
        "min_score": 0.8,
    },
    "detection": {
        # A reading must stay the same for this many frames before it counts. Filters animation flicker.
        "settle_frames": 2,
        # HP changes smaller than this (points) are ignored.
        "hp_noise": 1,
        # HP gains up to this size are natural regeneration; bigger gains are potions or heals.
        "hp_regen_max": 20,
        "mp_regen_max": 10,
        # An MP drop within this many points of a skill cost counts as that skill.
        "mp_tol": 1,
        # Ignore EXP readings that jump by more than this many kills at once (OCR misreads).
        "max_kills_per_step": 8,
    },
    "gui": {
        # While a session runs, read EXP off the status bar this often (seconds) and show EXP/hr so far
        # (0 = off).
        "live_every": 60,
    },
    "quickslot": {
        # Read the potions on the quick slots at Start and with every live EXP reading, and show the
        # mesos spent on HP and MP potions (at NPC shop price). The GUI has a checkbox for it too.
        "enabled": True,
        # Which item is on which key, if the item database can't tell: {"Del": "Orange Potion"}.
        "slots": {},
        # Kind and NPC shop price for potions missing from quickslot.POTIONS: {"Pizza": ["hp", 1000]}.
        "prices": {},
    },
    "session": {
        "monster": "Unknown",
        # EXP per kill of the monster you are farming. Used to split kills that land in the same frame.
        "monster_exp": None,
        "out_dir": "sessions",
        # Tesseract binary, if it is not on PATH (Windows example: C:/Program Files/Tesseract-OCR/tesseract.exe)
        "tesseract_cmd": None,
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class Config:
    data: dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEFAULT_CONFIG))
    path: Path | None = None

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        p = Path(path)
        raw = yaml.safe_load(p.read_text()) if p.exists() else {}
        return cls(_merge(DEFAULT_CONFIG, raw or {}), p)

    def save(self, path: str | Path | None = None) -> Path:
        p = Path(path or self.path or "config.yaml")
        p.write_text(yaml.safe_dump(self.data, sort_keys=False))
        self.path = p
        return p

    def configured_readers(self) -> dict[str, dict]:
        """Readers that have a box set; unconfigured ones are skipped."""
        return {k: v for k, v in self.data["readers"].items() if v.get("box")}
