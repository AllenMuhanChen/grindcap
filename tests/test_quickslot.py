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
    assert [p["used"]["Orange Potion"] for p in pts] == [0, 10, 10, 15, -100, -95]   # bought 115: net gain
    assert pts[-1]["hp"] == -95 * 160 and pts[-1]["mp"] == 5 * 190
    assert "Pet Food" not in pts[-1]["used"]                               # no price: not counted


def test_potion_series_rates_per_hour():
    from math import exp

    rows = [{"time": t, "potions": [{"key": "Del", "count": n, "name": "Red Potion"}]}
            for t, n in ((0, 100), (60, 90), (120, 70))]
    a, b, c = Q.potion_series({"time": 0.0}, rows, Q.prices())
    assert a["raw_hp"] is None and a["ema_hp"] is None                     # nothing to compare yet
    assert (b["raw_hp"], b["ema_hp"], b["cum_hp"]) == (10 * 50 * 60, 30000, 30000)   # 10 pots/min
    assert c["raw_hp"] == 60000 and c["cum_hp"] == 45000
    assert c["ema_hp"] == round(30000 + (1 - exp(-1 / 5)) * 30000, 1)
    assert c["raw_mp"] == 0


def test_describe_says_what_the_scan_found():
    t = Q.prices()
    assert Q.describe(None, t) == "Potions: quick slots not found"
    assert Q.describe([{"key": "Del", "count": 155, "name": "Orange Potion"},
                       {"key": "PgUp", "count": 12, "name": None}], t) == \
        "Potions: Del Orange Potion 155 · PgUp unknown item 12 (not counted)"


def test_quick_slot_items_are_matched_among_your_use_items_only():
    import numpy as np

    class DB:          # Brick fits the icon best, but it isn't a Use item you have
        max_score = 9000.0
        items = {4000000: {"name": "Brick", "category": "Etc"},
                 2000001: {"name": "Orange Potion", "category": "Use"},
                 2000000: {"name": "Red Potion", "category": "Use"},
                 2010000: {"name": "Lemon", "category": "Use"}}
        scores = {4000000: 100.0, 2000001: 300.0, 2000000: 900.0, 2010000: 2000.0}

        def rescore(self, patch, ignore, ids):
            return sorted((self.scores[i], i) for i in ids)

        def rank(self, patch, k=120):
            return sorted((s, i) for i, s in self.scores.items())

    class Cat:
        items = {"item-001": {"db": {"id": 2000001}}, "item-002": {"db": {"id": 2000000}},
                 "item-003": {"db": {"id": 4000000}}, "item-004": {}}

    db, patch, ignore = DB(), np.zeros((40, 40, 3), np.uint8), np.zeros((40, 40), bool)
    cands = Q.use_candidates(Cat(), db)
    assert cands == [2000001, 2000000]
    assert Q._identify(patch, ignore, db, "Del", {}, cands) == "Orange Potion"
    assert Q._identify(patch, ignore, db, "Del", {}) == "Orange Potion"     # no catalog: all Use items
    db.scores[2000000] = 310.0                                            # Red fits about as well: unsure
    assert Q._identify(patch, ignore, db, "End", {}, cands) is None


def test_quick_slots_are_named_from_the_start_inventory_counts():
    class Cat:
        items = {"item-001": {"name": "Orange Potion"}, "item-002": {"name": "Lemon"},
                 "item-003": {"name": "Blue Potion"}, "item-004": {"name": "Orange"},
                 "item-005": {"name": "Snail Shell"}}

    items = {"item-001": 155, "item-002": 248, "item-003": 20, "item-004": 20, "item-005": 158}
    pots = [{"key": "Del", "count": 155, "name": "Orange"},          # the icon guess was wrong: count wins
            {"key": "End", "count": 246, "name": "Orange Potion"},   # 2 used while paging: closest count
            {"key": "Ins", "count": 20, "name": "Blue Potion"},      # two items have 20: icon picks one
            {"key": "Hm", "count": 20, "name": None}]                # ... or nobody
    assert Q.match_by_count(pots, items, Cat()) == {"Del": "Orange Potion", "End": "Lemon",
                                                     "Ins": "Blue Potion"}


def test_session_names_override_what_was_logged():
    rows = [{"time": t, "potions": [{"key": "Del", "count": n, "name": "Orange"}]} for t, n in ((0, 50), (60, 40))]
    t = Q.prices({"Lemon": ["hp", 20]})
    assert Q.potion_series({"time": 0.0}, rows, t)[-1]["hp"] == 0                         # "Orange": no price
    assert Q.potion_series({"time": 0.0}, rows, t, key_names={"Del": "Lemon"})[-1]["hp"] == 200


def test_potion_gains_make_spending_negative():
    rows = [{"time": t, "potions": [{"key": "End", "count": n, "name": "Lemon"}]} for t, n in ((0, 100), (60, 103))]
    p = Q.potion_series({"time": 0.0}, rows, Q.prices())[-1]
    assert p["mp"] == -3 * 150 and p["raw_mp"] == -3 * 150 * 60          # picked up 3 Lemons in a minute
