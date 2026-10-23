# grindcap

Screen-capture tracker for MapleStory Classic World grinding sessions. It measures the per-monster values that the Grind Ledger simulator otherwise needs filled in by hand (touches per kill, seconds between kills, mesos per kill) plus EXP/hr, casts per kill and potion use.

The user (Allen) plays a warrior and is writing up an "eco" build: low Power Strike/Slash Blast levels, points into Iron Body, Improved HP Recovery and Max HP, Spearman with polearm and Final Attack (which heals). Measurements feed that write-up, so accuracy and explainability matter more than features.

## Hard rule

Read-only. Never send input to the game (no key presses, clicks or memory reads). Screen capture only.

## Architecture

```
capture.py   ScreenSource (mss, live) and VideoSource (cv2, replay). Both yield (t_seconds, BGR frame).
readers.py   BarReader: fill fraction of a coloured bar (rightmost filled column of the middle band,
             so text drawn over the bar doesn't break it). TextReader: Tesseract digits, cached per crop hash.
events.py    Stabilizer (value must hold settle_frames frames) + EventDetector: value changes -> events
             (touch, cast, kill, meso, hp/mp potion/regen, fa_heal, level_up).
session.py   Tracker (source -> readers -> detector -> JSONL log), summarize(), ledger_export().
calibrate.py cv2.selectROI box picking, bar colour sampling, snapshot/overlay for debugging.
inventory.py Grid (slot boxes from first/last visible slot), icon signatures with the stack-number area
             masked, Catalog (icon -> item-NNN id, name, price; data/catalog.json + icons/), read_page,
             merge_pages (stitches scrolled pages by largest identical row overlap), totals.
digits.py    StackDigits: stack numbers in the game's font. Maps the screen back to native game pixels
             (scale from slot pitch = 36 native px, sub-pixel phase by Laplacian sharpness), then reads
             left to right at fixed advances (8 px, "1" = 5 px) by masked normalised correlation.
             Built-in templates: data/stack_digits.npz, rebuilt by scripts/build_stack_digits.py from
             tests/fixtures/game_frame.png. `teach-digits` = check + corrections (data/digits.npz).
itemdb.py    ItemDB: maplestory.io item data for region MCW (= Classic World), version 1: names, icons,
             NPC sell price (per item, lazily). identify(native BGR patch): masked TM_SQDIFF of every
             Etc/Use/Setup icon (alpha>200) slid over the slot; accept if best name beats the next name
             by min_ratio 1.25. inventory._identify_slot: catalog signature -> fast re-check against the
             item's db icon + its stored look-alike neighbours -> else full identify; one catalog id per
             db id (extra looks saved as icons/<id>.altN.npy). On the real frame 18/18 correct, ratio >= 1.29.
             Categories Etc/Use/Setup/Equip (non-cash, ~2470 icons); rank() first shortlists 120 icons by
             half-size matching (true best ranked <= 57 on fixtures). inventory.detect_tab reads the active
             (pink) tab button; build_snapshot groups pages by tab, skips inventory.skip_tabs (Cash, Deco).
             merge rows agree only on same item AND count (repeated stacks of one item otherwise collapse).
review.py    Session review: list_sessions (end paired with latest start before it), review_data (changed
             items + their slots, covered "?" slots, status), apply_edit (slot/slot_db/reset/status/
             ignore_item/purge/purge_deleted/item/item_db), local http.server + data/review.html. Slot/status fixes live in
             <snapshot>/fixes.json ("slots", "status", "deleted" item ids), applied by snapshot.apply_fixes in
             compare(); compare() also skips ids no longer in the catalog (purged). Prices: catalog "price"
             = user's, "npc_price" = NPC; Catalog.price() picks. Slots under a tooltip (is_covered) are
             UNKNOWN "?": not counted, ignored when matching pages, filled from an overlapping page.
sessions.py  list_sessions (each end snapshot + latest start before it; id = end folder name), name/map/saved
             overrides in <snapshot_dir>/sessions.json, default name "<map> · <start> · <min> min", delete
             (keeps a start another session uses). review.py re-exports list_sessions.
mapname.py   Minimap map name: template-match data/minimap_header.png ("MINI MAP" bar, 1920x1080; scaled
             by frame height), Tesseract on the street + map lines, snapped to MCW map names (maps.json in
             <catalog_dir>/itemdb, from maplestory.io /map) by difflib. Stored as snapshot["map"].
statusbar.py read_level (orange LV tiles -> white mask -> Tesseract psm 8, one digit per tile, vote; in the
             level box +-25 px, else searched in the bottom-left of the window), read_exp_texts (right of
             the "EXP." label found by template data/exp_label.png; calibrated box only as fallback),
             resolve: try every exp/pct split ("[" OCRs as 1) and keep one where exp/EXP_TO_NEXT[lv]*100
             rounds to pct (+-0.0051). Tile level that fits wins; else levels prior..prior+5 (prior = latest
             earlier snapshot with a confirmed level, or config level +69), several fitting -> level_options
             shown on the review page. Verified on both fixtures (26/53791, 27/10), also with bad boxes.
snapshot.py  Before/after mode: build_snapshot, compare (EXP across level-ups, mesos, item deltas/hr,
             value from catalog prices), text + HTML report, PageCollector (F8/F9/F10 via pynput).
cli.py       calibrate | snapshot | watch | run | replay | summarize | export |
             snap start/end | compare | items | label | teach-digits
anchors.py   Template-matched anchors (inventory title bar, status-bar label) found per frame; boxes that
             belong to that window are shifted by the anchor's offset (shifted()). User wants minimal manual input.
wincap.py    GameWindow: capture the game window by title. Windows Graphics Capture (works when covered,
             not when minimized) -> PrintWindow -> plain screenshot. winfind.py: Win32 window lookup.
app.py       SnapFlow: toolkit-free snapshot workflow (start, add_page, poll with PageWatcher, finish, compare).
gui.py       tkinter always-on-top control window over SnapFlow; work runs in threads, button presses take
             priority over auto-capture polls. Entry point grindcap-gui (no console). One session at a
             time: sessions.running() (newest start newer than every end) greys out Start, enables End,
             shows a running timer + map and a Discard button (deletes that start snapshot).
             User cares most about Net mesos/hr incl. items and EXP/hr: those lead every summary.
gamedata.py  EXP-to-next-level table (pre-Big-Bang values, levels 1-69).
config.py    Defaults + YAML merge. All reader boxes are [x, y, w, h] relative to capture.region.
```

Session logs are JSONL: first line `{"kind": "session", ...}` header, then one event per line with `t` in seconds from start.

## Conventions

- Pure logic (events, summarize) takes plain values so it can be tested without a screen. Keep it that way.
- New readers implement `read(frame) -> Reading`.
- Tests use synthetic frames from `tests/synth.py` (fake status bar drawn with OpenCV). The end-to-end tests need Tesseract installed and skip otherwise.
- Run tests: `python -m pytest -q`

## Not verified against the real game yet

Everything was built and tested on synthetic frames; the real UI has not been seen. First steps on the user's machine:

1. `grindcap calibrate`, then `grindcap snapshot` and look at the crops in `captures/`.
2. `grindcap watch` while taking hits and casting: check HP/MP/EXP/meso readings move correctly.
3. Tune `settle_frames`, regen thresholds and `mp_tol` from what `watch` shows.
4. If Tesseract misreads the game's pixel font, replace TextReader with template matching on digit glyphs cut from a screenshot (the font is fixed, so this is usually more reliable than OCR).

Snapshot mode specifics to check on the real game: icon match threshold (same item must match across
captures, different items must not), empty-slot detection threshold, and whether hover highlights change
icons. Stack digits are verified on one real 1920x1080 frame (tests/fixtures/game_frame.png, Etc tab,
5 columns x 6 rows): digit costs <= 0.23, non-digits >= 0.72, END_COST 0.45.

The user's preferred first workflow is snapshots (start/end) from the control window, not live tracking.
The user has one monitor and wants as little manual input as possible. HP/MP are read as numbers (cur/max);
the slash often OCRs as a digit, handled in TextReader.parse_pair.

gui.py was only smoke-tested headless with a fake tkinter; wincap.py has not run on Windows yet.

## Next steps

- Item drops: OCR the pickup messages in the chat/system log ("You have gained an item ...") and count by item, so drop rates can replace the OSMLib reference rates.
- Separate "touches" from fall damage and skill HP costs (Slash Blast costs HP).
- Attribute kills to monsters by EXP value when a map has several monster types.
- Write `ledger_export` output in a format Grind Ledger can import directly.
