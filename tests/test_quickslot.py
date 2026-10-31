"""Quick slot potions: counts read off real screenshots, and mesos spent from the readings."""
from pathlib import Path

import cv2
import pytest

from grindcap import quickslot as Q
from grindcap.digits import StackDigits

FIX = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("name, counts", [
    ("game_frame", {"PgUp": 12, "Del": 155, "End": 20}),
    ("use_tab_tooltip", {"PgUp": 8, "Del": 158, "End": 20}),
    ("etc_ant_tunnel", {"PgUp": 45, "Del": 84, "End": 10}),
    ("etc_excavation", {"PgUp": 0, "Del": 256, "End": 2, "PgDn": 102}),
    ("equip_burnt_land", {"PgUp": 15, "Del": 155, "End": 248}),
])
def test_quick_slot_counts_on_real_screenshots(name, counts):
    frame = cv2.imread(str(FIX / f"{name}.png"))
    got = Q.read_quickslot(frame, StackDigits(), names={"Del": "Orange Potion"})
    assert {p["key"]: p["count"] for p in got} == counts     # skills ("ATTACK" on Ctrl) have no number
    assert next(p for p in got if p["key"] == "Del")["name"] == "Orange Potion"   # config names a slot


def test_no_panel_no_reading():
    import numpy as np

    assert Q.read_quickslot(np.zeros((1080, 1920, 3), np.uint8), StackDigits()) == []


def test_potion_series_counts_drops_at_shop_price():
    start = {"time": 0.0, "pauses": [[300, 900]]}
    pot = lambda o, b, x=None: [{"key": "Del", "count": o, "name": "Orange Potion"},
                                {"key": "End", "count": b, "name": "Blue Potion"},
                                {"key": "PgUp", "count": 9, "name": x}]
    rows = [{"time": 0, "potions": pot(100, 50)},
            {"time": 60, "exp": 1, "level": 20, "checked": True},          # no potion reading: skipped
            {"time": 120, "potions": pot(90, 48)},
            {"time": 180, "potions": pot(9, 47)},                          # misread 90 -> 9
            {"time": 240, "potions": pot(85, 47)},
            {"time": 960, "potions": pot(200, 45, "Pet Food")},            # bought more orange potions
            {"time": 1020, "potions": pot(195, 45)}]
    pts = Q.potion_series(start, rows, Q.prices({"Blue Potion": ["mp", 190]}))
    assert [p["t"] for p in pts] == [0, 2, 3, 4, 6, 7]                    # 10 min paused left out
    assert [p["used"]["Orange Potion"] for p in pts] == [0, 10, 10, 15, 15, 20]
    assert pts[-1]["hp"] == 20 * 160 and pts[-1]["mp"] == 5 * 190
    assert "Pet Food" not in pts[-1]["used"]                               # no price: not counted
