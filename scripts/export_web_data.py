"""Export the item data and your taught stack digits for the browser prototype (web/).

Reads what the Python app already has on this PC and writes web/local/ (not in git):

  web/local/itemdb.json   item names, tabs, prices and icons (from <catalog_dir>/itemdb, downloaded from
                          maplestory.io by the Python app; your own prices from catalog.json win)
  web/local/maps.json     Classic World map names (<catalog_dir>/itemdb/maps.json), to snap the minimap text to
  web/local/quickslot.json  quickslot settings from config.yaml (enabled, slots, prices)
  web/local/digits.json   your teach-digits examples (<catalog_dir>/digits.npz), added to the built-in ones

Run from the repo root:  python scripts/export_web_data.py   (--no-prices: don't fetch missing NPC prices)
If the item data hasn't been downloaded yet, run `grindcap itemdb` (or take one snapshot) first.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def fetch_prices(items: dict, items_path: Path, cfg) -> None:
    """NPC sell price for every item that doesn't have one yet. The Python app only fetched prices for
    items it had identified, so most items had none. Saved into items.json (no-price items as null, so
    they aren't asked again). About 2,500 requests the first time, a couple of minutes; later runs are instant."""
    from concurrent.futures import ThreadPoolExecutor
    from grindcap.itemdb import _get

    opt = cfg["inventory"].get("itemdb") or {}
    base = f"https://maplestory.io/api/{opt.get('region', 'MCW')}/{opt.get('version', '1')}"
    todo = [iid for iid, it in items.items() if "price" not in it]
    if not todo:
        return
    print(f"Fetching NPC prices for {len(todo)} items from maplestory.io (once; --no-prices skips)...")

    def one(iid):
        try:
            meta = json.loads(_get(f"{base}/item/{iid}", 20, tries=2)).get("metaInfo") or {}
            return iid, meta.get("price"), True
        except Exception:
            return iid, None, False

    done = failed = 0
    with ThreadPoolExecutor(8) as ex:
        for n, (iid, price, ok) in enumerate(ex.map(one, todo), 1):
            if ok:
                items[iid]["price"] = price
                done += 1
            else:
                failed += 1
            if n % 250 == 0:
                print(f"  prices {n}/{len(todo)}")
                items_path.write_text(json.dumps(items, indent=1))
    items_path.write_text(json.dumps(items, indent=1))
    have = sum(1 for it in items.values() if it.get("price"))
    print(f"Prices: {done} fetched, {failed} failed (run again to retry them); {have} of {len(items)} items have an NPC price.")


def main() -> int:
    from grindcap.config import Config

    cfg = Config.load(ROOT / "config.yaml")
    data = Path(cfg["inventory"]["catalog_dir"])
    if not data.is_absolute():
        data = ROOT / data
    out = ROOT / "web" / "local"
    out.mkdir(parents=True, exist_ok=True)

    # --- item data
    itemdb = data / "itemdb"
    items_path = itemdb / "items.json"
    if not items_path.exists():
        print(f"No item data in {itemdb}. Run `grindcap itemdb` first, then run this again.")
        return 1
    if "--no-icons" not in sys.argv:          # icons that failed to download before (tried again each run)
        from grindcap.itemdb import ItemDB
        opt = cfg["inventory"].get("itemdb") or {}
        db = ItemDB(itemdb, opt.get("region", "MCW"), str(opt.get("version", "1")))
        if any(not (itemdb / "icons" / f"{i}.png").exists() for i in db.items):
            print("Fetching missing icons...")
            db.fill_icons()
    items = json.loads(items_path.read_text())
    if "--no-prices" not in sys.argv:
        fetch_prices(items, items_path, cfg)
    user_prices = {}
    cat_path = data / "catalog.json"
    if cat_path.exists():
        for it in json.loads(cat_path.read_text()).values():
            db = (it.get("db") or {}).get("id")
            if db is not None:
                user_prices[str(db)] = {"price": it.get("price"), "npc_price": it.get("npc_price")}
    exp_items, icons, no_icon = {}, {}, []
    for iid, it in items.items():
        p = itemdb / "icons" / f"{iid}.png"
        up = user_prices.get(str(iid), {})
        price = up.get("price") if up.get("price") is not None else (up.get("npc_price") or it.get("price"))
        exp_items[iid] = {"name": it["name"], "category": it.get("category"), "price": price}
        if p.exists():
            icons[iid] = base64.b64encode(p.read_bytes()).decode()
        else:   # maplestory.io had no icon (e.g. Skeledog's Bone 4000154): still searchable by name, never auto-matched
            no_icon.append(it["name"])
    (out / "itemdb.json").write_text(json.dumps({"items": exp_items, "icons": icons}))
    print(f"Items: {len(exp_items)} ({len(icons)} with icons) -> {out / 'itemdb.json'}")
    if no_icon:
        print(f"  {len(no_icon)} without an icon (name search only): {', '.join(sorted(no_icon)[:15])}{' ...' if len(no_icon) > 15 else ''}")

    # --- map names
    mp = itemdb / "maps.json"
    if not mp.exists():
        try:
            from grindcap.mapname import download_maps
            download_maps(itemdb)
        except Exception as e:  # offline: map names are read but not snapped to real ones
            print(f"Map names not downloaded ({e}); the minimap text is used as read.")
    if mp.exists():
        maps = [{"streetName": m.get("streetName") or "", "name": m.get("name") or ""} for m in json.loads(mp.read_text())]
        (out / "maps.json").write_text(json.dumps(maps))
        print(f"Map names: {len(maps)} -> {out / 'maps.json'}")

    # --- quick slot settings (which item is on which key, extra potion prices)
    q = cfg.data.get("quickslot") or {}
    qs = {"enabled": bool(q.get("enabled", True)), "slots": q.get("slots") or {}, "prices": q.get("prices") or {}}
    (out / "quickslot.json").write_text(json.dumps(qs))
    print(f"Quick slots: {qs} -> {out / 'quickslot.json'}")

    # --- taught digits
    taught = data / "digits.npz"
    if taught.exists():
        z = np.load(taught)
        d = {"offset": [int(v) for v in z["offset"]] if "offset" in z else None,
             "digits": {k[1]: [a.astype(float).round(2).flatten().tolist() for a in z[k]]
                        for k in z.files if k.startswith("d")}}
        (out / "digits.json").write_text(json.dumps(d))
        print(f"Taught digits: {sum(len(v) for v in d['digits'].values())} examples -> {out / 'digits.json'}")
    else:
        (out / "digits.json").unlink(missing_ok=True)
        print("No taught digits (data/digits.npz): the built-in templates will be used.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
