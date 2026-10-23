"""Reviewing a session: slot fixes, deleting misreads, status fixes, prices."""
import json

from grindcap.inventory import Catalog
from grindcap.review import apply_edit, list_sessions, review_data
from grindcap.snapshot import compare, load_snapshot


def snap(folder, t, slots, exp=1000, mesos=500):
    folder.mkdir(parents=True)
    items = {}
    for ref, iid, n in slots:
        if iid != "?":
            items[iid] = items.get(iid, 0) + n
    (folder / "snapshot.json").write_text(json.dumps({
        "time": t, "when": "", "level": 20, "level_read": True, "exp": exp, "mesos": mesos, "items": items,
        "slots": [{"ref": r, "item": i, "qty": n, "box": None} for r, i, n in slots]}))
    return folder


def setup(tmp_path):
    cat = Catalog(tmp_path / "data")
    for iid, name, npc in [("item-001", "Red Potion", 25), ("item-002", "Snail Shell", 3), ("item-003", None, None)]:
        cat.items[iid] = {"name": name, "price": None, "npc_price": npc}
    cat.save()
    root = tmp_path / "snaps"
    s = snap(root / "start-1", 0, [("Use_01:r1c1", "item-001", 100), ("Etc_01:r1c1", "item-002", 10),
                                   ("Etc_01:r1c2", "?", 0)])
    e = snap(root / "end-1", 3600, [("Use_01:r1c1", "item-001", 60), ("Etc_01:r1c1", "item-002", 50),
                                    ("Etc_01:r1c2", "item-003", 7)], exp=3000, mesos=900)
    return Catalog(tmp_path / "data"), root, s, e


def test_sessions_pair_each_end_with_the_start_before_it(tmp_path):
    _, root, s, e = setup(tmp_path)
    snap(root / "start-2", 5000, [])
    snap(root / "end-2", 9000, [])
    ss = list_sessions(root)
    assert [(x["id"], x["start"].split("/")[-1]) for x in ss] == [("end-2", "start-2"), ("end-1", "start-1")]


def test_fixing_a_slot_deleting_a_misread_and_status(tmp_path):
    cat, root, s, e = setup(tmp_path)
    d = review_data(s, e, cat)
    assert {it["id"]: it["change"] for it in d["items"]} == {"item-001": -40, "item-002": 40, "item-003": 7}
    assert [x["ref"] for x in d["covered"]["start"]] == ["Etc_01:r1c2"]

    # the hidden start slot was really 2 Snail Shells; the end count of potions was misread (should be 61)
    apply_edit(s, e, cat, None, {"op": "slot", "snap": "start", "ref": "Etc_01:r1c2", "item": "item-002", "qty": 2})
    apply_edit(s, e, cat, None, {"op": "slot", "snap": "end", "ref": "Use_01:r1c1", "qty": 61})
    # item-003 is junk (a menu covered the slot): delete it from the session
    apply_edit(s, e, cat, None, {"op": "ignore_item", "id": "item-003"})
    apply_edit(s, e, cat, None, {"op": "status", "snap": "end", "field": "exp", "value": "3100"})
    r = compare(load_snapshot(s), load_snapshot(e), cat)
    assert {it["id"]: it["change"] for it in r["items"]} == {"item-001": -39, "item-002": 38}
    assert r["exp"] == 2100
    d = review_data(s, e, cat)
    assert next(it for it in d["items"] if it["id"] == "item-003")["deleted"]
    assert d["covered"]["start"] == []

    # undo: restore the deleted item, reset the slot fix
    apply_edit(s, e, cat, None, {"op": "ignore_item", "id": "item-003", "ignore": False})
    apply_edit(s, e, cat, None, {"op": "reset", "snap": "end", "ref": "Use_01:r1c1"})
    r = compare(load_snapshot(s), load_snapshot(e), cat)
    assert {it["id"]: it["change"] for it in r["items"]} == {"item-001": -40, "item-002": 38, "item-003": 7}


def test_custom_price_keeps_npc_price(tmp_path):
    cat, root, s, e = setup(tmp_path)
    apply_edit(s, e, cat, None, {"op": "item", "id": "item-001", "price": "50"})
    r = compare(load_snapshot(s), load_snapshot(e), Catalog(tmp_path / "data"))
    assert next(it for it in r["items"] if it["id"] == "item-001")["value"] == -40 * 50
    cat = Catalog(tmp_path / "data")
    assert cat.items["item-001"]["npc_price"] == 25
    apply_edit(s, e, cat, None, {"op": "item", "id": "item-001", "price": ""})   # back to NPC price
    assert Catalog(tmp_path / "data").price("item-001") == 25
