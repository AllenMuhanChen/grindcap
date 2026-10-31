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
             Two digits within TIE 0.06 (3 vs 8 with an icon in the holes) are decided by grey-level
             distance on the pixels where the two templates differ (>60 levels). Fixture etc_excavation.png.
itemdb.py    ItemDB: maplestory.io item data for region MCW (= Classic World), version 1: names, icons,
             NPC sell price (per item, lazily). identify(native BGR patch): masked TM_SQDIFF of every
             Etc/Use/Setup icon (alpha>200) slid over the slot; accept if best name beats the next name
             by min_ratio 1.25. inventory._identify_slot: catalog signature -> fast re-check against the
             item's db icon + its stored look-alike neighbours -> else full identify; one catalog id per
             db id (extra looks saved as icons/<id>.altN.npy). The fast re-check scores the db ids of ALL
             catalog candidates within threshold (+ the closest one's neighbours): ores that differ only in
             colour are all within the signature threshold, so the closest candidate can be wrong. On the real frame 18/18 correct, ratio >= 1.29.
             Categories Etc/Use/Setup/Equip (non-cash, ~2470 icons); rank() first shortlists 120 icons by
             half-size matching (true best ranked <= 57 on fixtures). inventory.detect_tab reads the active
             (pink) tab button (largest red block: a tab with new items flashes), but the items decide
             first: tab_from_items (db category of named items, 2+ and 70%) after reading, quick_tab
             (catalog signatures only) while capturing; build_snapshot groups pages by tab, skips
             inventory.skip_tabs (Cash, Deco).
             merge rows agree only on same item AND count (repeated stacks of one item otherwise collapse).
review.py    Session review: list_sessions (end paired with latest start before it), review_data (changed
             items + their slots, covered "?" slots, status), apply_edit (slot/slot_db/reset/status/
             ignore_item/purge/purge_deleted/item/item_db), local http.server + data/review.html. Slot/status fixes live in
             <snapshot>/fixes.json ("slots", "status", "deleted" item ids), applied by snapshot.apply_fixes in
             compare(); compare() also skips ids no longer in the catalog (purged). Prices: catalog "price"
             = user's, "npc_price" = NPC; Catalog.price() picks. Slots under a tooltip (is_covered) are
             UNKNOWN "?": not counted, ignored when matching pages, filled from an overlapping page.
summary      data/summary.html at /summary on the review server (review.summary_data): scatter of
             EXP/hr vs net (or raw) mesos/hr, one dot per saved session (or all), hover tooltip, click opens
             the session, table below. Single hue (identity via hover/table). User will add more here.
sessions.py  list_sessions (each end snapshot + latest start before it; id = end folder name), name/map/saved
             overrides in <snapshot_dir>/sessions.json, default name "<map> · <start> · <min> min", delete
             (keeps a start another session uses). review.py re-exports list_sessions.
mapname.py   Minimap map name: template-match data/minimap_header.png ("MINI MAP" bar, 1920x1080; scaled
             by frame height), Tesseract on the street + map lines, snapped to MCW map names (maps.json in
             <catalog_dir>/itemdb, from maplestory.io /map) by difflib. A last word of I-like strokes
             ("ill", "l1") is turned into a Roman numeral first. Several OCR variants per line
             (plain + white-letters-only); the pair closest to a real map wins. Stored as snapshot["map"].
statusbar.py read_level (orange LV tiles, kept only if square-ish, >=50% orange, with white on them:
             orange scenery left of the status bar otherwise became a 1-digit level -> white mask -> Tesseract psm 8, one digit per tile, vote; in the
             level box +-25 px, else searched in the bottom-left of the window), read_exp_texts (right of
             the "EXP." label found by template data/exp_label.png; calibrated box only as fallback),
             resolve: try every exp/pct split ("[" OCRs as 1) and keep one where exp/EXP_TO_NEXT[lv]*100
             rounds to pct (+-0.0051). Tile level that fits wins; else levels prior..prior+5 (prior = latest
             earlier snapshot with a confirmed level, or config level +69), several fitting -> level_options
             shown on the review page. Verified on fixtures (26/53791, 27/10, 33/2595), also with bad boxes.
             read_mesos_field: the white meso field below the grid (located from the grid, not a box),
             dark digits, groups-of-3 check, 2 sizes agreeing; None if covered. build_snapshot reads it on
             every page and takes the majority (mesos_checked). Fixture etc_ant_tunnel.png: 222,540.
             Field rows = the longest run of white rows (the light panel above is near-white too; spanning
             it cropped in the field's border, read as a leading "1"). The page + box used is saved as
             snapshot["mesos_field"]; the review page shows that crop next to the mesos inputs (/mesocrop;
             older snapshots derive the box from two slot boxes). Fixture equip_burnt_land.png: 492,177.
snapshot.py  Before/after mode: build_snapshot, compare (EXP across level-ups, mesos, item deltas/hr,
             value from catalog prices), text + HTML report, PageCollector (F8/F9/F10 via pynput).
cli.py       calibrate | snapshot | watch | run | replay | summarize | export |
             snap start/end | compare | items | label | teach-digits
anchors.py   Template-matched anchors (inventory title bar, status-bar label) found per frame; boxes that
             belong to that window are shifted by the anchor's offset (shifted()). User wants minimal manual input.
wincap.py    GameWindow: capture the game window by title. Windows Graphics Capture (works when covered,
             not when minimized) -> PrintWindow -> plain screenshot. winfind.py: Win32 window lookup.
app.py       SnapFlow: toolkit-free snapshot workflow (start, add_page, poll with PageWatcher, finish, compare).
grindcap.bat Windows double-click launcher (cd to repo, start .venv\Scripts\grindcap-gui.exe); grindcap-debug.bat
             keeps a console for errors; make-shortcut.bat makes a Desktop .lnk to grindcap.bat.
gui.py       tkinter always-on-top control window over SnapFlow; work runs in threads, button presses take
             priority over auto-capture polls. Entry point grindcap-gui (no console). One session at a
             time: sessions.running() (newest start newer than every end) greys out Start, enables End,
             shows a running timer + map and a Discard button (deletes that start snapshot).
             User cares most about Net mesos/hr incl. items and EXP/hr: those lead every summary
             (then revenue/hr and cost/hr). Finish runs in the background with progress messages;
             auto-finish when SnapFlow.finish_in() hits 0 (all non-skipped tabs seen via detect_tab,
             no new page for auto_finish_after s). Snapshot time: start = last page captured, end =
             End pressed. build_snapshot(status=...) reuses the Start readings; duplicate pages and
             unnamed items already searched (db_tried) are skipped, so a known inventory reads in ~1 s.
             wincap.grab retries 3x and never switches WGC off for good after a black frame.
             Pause/Resume while a session runs: sessions.set_paused writes <start>/pauses.json
             ([[t0, t1|null], ...]); compare() and list_sessions leave paused time out of minutes and
             every per-hour rate (paused_minutes in the result). Every gui.live_every s (60) while running
             and not paused, SnapFlow.live reads EXP/level off the status bar and shows "EXP/hr: N  x%/hr"
             under the timer (only EXP-table-confirmed readings; logged to <start>/live.jsonl), plus a
             tk Canvas graph from snapshot.live_series: per-reading EXP/hr (dots), 5-min EMA (dt-weighted,
             solid), session-so-far (dashed); x = active minutes. The review page shows the same graph
             (review_data["live"], live rows up to the end + the end snapshot; [] for older sessions). Finishing
             the end snapshot runs compare and shows key_figures (net mesos/hr, EXP/hr, ...) right away.
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
