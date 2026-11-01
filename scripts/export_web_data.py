"""Export the item data and your taught stack digits for the browser prototype (web/).

Reads what the Python app already has on this PC and writes web/local/ (not in git):

  web/local/itemdb.json   item names, tabs, prices and icons (from <catalog_dir>/itemdb, downloaded from
                          maplestory.io by the Python app; your own prices from catalog.json win)
  web/local/digits.json   your teach-digits examples (<catalog_dir>/digits.npz), added to the built-in ones

Run from the repo root:  python scripts/export_web_data.py
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
    items = json.loads(items_path.read_text())
    user_prices = {}
    cat_path = data / "catalog.json"
    if cat_path.exists():
        for it in json.loads(cat_path.read_text()).values():
            db = (it.get("db") or {}).get("id")
            if db is not None:
                user_prices[str(db)] = {"price": it.get("price"), "npc_price": it.get("npc_price")}
    exp_items, icons = {}, {}
    for iid, it in items.items():
        p = itemdb / "icons" / f"{iid}.png"
        if not p.exists():
            continue
        up = user_prices.get(str(iid), {})
        price = up.get("price") if up.get("price") is not None else (up.get("npc_price") or it.get("price"))
        exp_items[iid] = {"name": it["name"], "category": it.get("category"), "price": price}
        icons[iid] = base64.b64encode(p.read_bytes()).decode()
    (out / "itemdb.json").write_text(json.dumps({"items": exp_items, "icons": icons}))
    print(f"Items: {len(exp_items)} with icons -> {out / 'itemdb.json'}")

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
