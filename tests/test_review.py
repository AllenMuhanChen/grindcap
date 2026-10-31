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


def test_delete_works_without_slot_records_and_purge_removes_item(tmp_path):
    cat, root, s, e = setup(tmp_path)
    for f in (s, e):   # a snapshot saved before slots were recorded
        d = json.loads((f / "snapshot.json").read_text())
        d.pop("slots")
        (f / "snapshot.json").write_text(json.dumps(d))
    apply_edit(s, e, cat, None, {"op": "ignore_item", "id": "item-003"})
    r = compare(load_snapshot(s), load_snapshot(e), cat)
    assert "item-003" not in {it["id"] for it in r["items"]}
    d = review_data(s, e, cat)
    dl = next(it for it in d["items"] if it["id"] == "item-003")
    assert dl["deleted"] and (dl["read_before"], dl["read_after"]) == (0, 7)
    (cat.icons_dir).mkdir(parents=True, exist_ok=True)
    (cat.icons_dir / "item-003.png").write_bytes(b"x")
    apply_edit(s, e, cat, None, {"op": "purge_deleted"})
    cat = Catalog(tmp_path / "data")
    assert "item-003" not in cat.items and not (cat.icons_dir / "item-003.png").exists()
    assert "item-003" not in {it["id"] for it in review_data(s, e, cat)["items"]}
    assert "deleted" not in load_snapshot(e)["fixes"]


def test_custom_price_keeps_npc_price(tmp_path):
    cat, root, s, e = setup(tmp_path)
    apply_edit(s, e, cat, None, {"op": "item", "id": "item-001", "price": "50"})
    r = compare(load_snapshot(s), load_snapshot(e), Catalog(tmp_path / "data"))
    assert next(it for it in r["items"] if it["id"] == "item-001")["value"] == -40 * 50
    cat = Catalog(tmp_path / "data")
    assert cat.items["item-001"]["npc_price"] == 25
    apply_edit(s, e, cat, None, {"op": "item", "id": "item-001", "price": ""})   # back to NPC price
    assert Catalog(tmp_path / "data").price("item-001") == 25


def test_session_names_saved_flag_and_delete(tmp_path):
    from grindcap import sessions

    _, root, s, e = setup(tmp_path)
    d = json.loads((s / "snapshot.json").read_text())
    d["map"] = {"street": "Victoria Road", "name": "The Rain-Forest East of Henesys"}
    (s / "snapshot.json").write_text(json.dumps(d))
    snap(root / "end-2", 7200, [])          # a second session sharing the same start
    ss = {x["id"]: x for x in sessions.list_sessions(root)}
    assert ss["end-1"]["map"] == "The Rain-Forest East of Henesys"
    assert ss["end-1"]["name"].startswith("The Rain-Forest East of Henesys · ") and ss["end-1"]["name"].endswith("60 min")
    sessions.update(root, "end-1", name="Pigs, FA test", saved=True, map="Pig Beach")
    x = {x["id"]: x for x in sessions.list_sessions(root)}["end-1"]
    assert (x["name"], x["map"], x["saved"], x["map_read"]) == ("Pigs, FA test", "Pig Beach", True,
                                                                 "The Rain-Forest East of Henesys")
    sessions.update(root, "end-1", name="", map="")      # back to automatic
    x = {x["id"]: x for x in sessions.list_sessions(root)}["end-1"]
    assert x["map"] == "The Rain-Forest East of Henesys" and x["saved"]
    removed = sessions.delete(root, "end-1")
    assert [p.split("/")[-1] for p in removed] == ["end-1"]      # start kept: end-2 still uses it
    assert not e.exists() and s.exists()
    sessions.delete(root, "end-2")
    assert not s.exists() and sessions.list_sessions(root) == []


def test_revenue_and_cost(tmp_path):
    cat, root, s, e = setup(tmp_path)
    r = compare(load_snapshot(s), load_snapshot(e), cat)
    # mesos 500 -> 900; Snail Shell +40 at NPC 3; Red Potion -40 at NPC 25; item-003 has no price
    assert (r["revenue"], r["cost"]) == (400 + 120, 1000)
    assert r["revenue_per_hr"] == 520 and r["cost_per_hr"] == 1000      # the session is one hour
    assert r["net_mesos_incl_items"] == r["revenue"] - r["cost"]


def test_summary_points_saved_sessions(tmp_path):
    from grindcap import sessions
    from grindcap.review import summary_data

    cat, root, s, e = setup(tmp_path)
    assert summary_data(root, cat)["sessions"] == []                 # nothing saved yet
    sessions.update(root, "end-1", saved=True)
    [p] = summary_data(root, cat)["sessions"]
    assert (p["id"], p["exp_per_hr"], p["mesos_per_hr"]) == ("end-1", 2000, 400)
    assert p["net_per_hr"] == 400 + 120 - 1000
    assert len(summary_data(root, cat, saved_only=False)["sessions"]) == 1


def test_meso_field_picture(tmp_path):
    """The review page shows the meso field as captured; older snapshots find it from two slot boxes."""
    import shutil
    from pathlib import Path

    import cv2

    from grindcap.inventory import Grid
    from grindcap.review import meso_crop_png, meso_field
    from grindcap.statusbar import meso_field_box

    g = Grid([1486, 137, 44, 44], [1688, 378, 44, 44], cols=5, rows=6)
    b = g.slot_boxes()
    folder = tmp_path / "end-1"
    snap(folder, 0, [])
    data = json.loads((folder / "snapshot.json").read_text())
    data["slots"] = [{"ref": "Equip_01:r1c1", "item": "item-001", "qty": 1, "box": list(b[0][0])},
                     {"ref": "Equip_01:r3c4", "item": "item-001", "qty": 1, "box": list(b[2][3])}]
    (folder / "snapshot.json").write_text(json.dumps(data))
    shutil.copy(Path(__file__).parent / "fixtures" / "equip_burnt_land.png", folder / "Equip_01.png")
    where = meso_field(load_snapshot(folder))
    assert where["page"] == "Equip_01"
    assert max(abs(p - q) for p, q in zip(where["box"], meso_field_box(g))) <= 1
    png = meso_crop_png(folder)
    img = cv2.imdecode(__import__("numpy").frombuffer(png, "uint8"), cv2.IMREAD_COLOR)
    assert img.shape[1] == 2 * where["box"][2]
    data["mesos_field"] = {"page": "Equip_01", "box": [1, 2, 3, 4]}       # saved by build_snapshot
    (folder / "snapshot.json").write_text(json.dumps(data))
    assert meso_field(load_snapshot(folder))["box"] == [1, 2, 3, 4]


def test_review_has_the_exp_per_hour_graph_only_with_live_readings(tmp_path):
    cat, root, s, e = setup(tmp_path)
    assert review_data(s, e, cat)["live"] == []            # an older session: no graph
    rows = [{"time": 1800, "exp": 2000, "level": 20, "checked": True},
            {"time": 4000, "exp": 3500, "level": 20, "checked": True}]   # after the end snapshot: left out
    (s / "live.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    pts = review_data(s, e, cat)["live"]
    assert [p["t"] for p in pts] == [30, 60]               # the end snapshot is the last point
    assert pts[-1]["cum"] == 2000                           # = the session's EXP/hr
