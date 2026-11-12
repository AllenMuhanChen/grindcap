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
             Capturing: SnapFlow.add_page rejects (returns None, GUI beeps + warns) a page where covered_slots
             finds tooltip colour in solid 6x6 patches over >4% of any slot (clean fixtures 0, tooltip 40-75%;
             a purple Equip helmet had 12% scattered pixels, so plain is_covered fractions can't be used);
             PageWatcher.reject_last lets the same view without the tooltip be captured next.
             merge rows agree only on same item AND count (repeated stacks of one item otherwise collapse).
review.py    Session review: list_sessions (end paired with latest start before it), review_data (changed
             items + their slots, covered "?" slots, status), apply_edit (slot/slot_db/reset/status/
             ignore_item (id or ids)/purge/purge_deleted/item/item_db), local http.server + data/review.html
             (Delete removes the row at once and reloads 1.2 s after the last click; tick boxes + "Delete N
             selected" send one ids edit). Slot/status fixes live in
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
snapshot.py  Before/after mode: build_snapshot, compare (EXP across level-ups, mesos, item deltas/hr;
             only items from tabs read in BOTH snapshots: tabs_left_out/items_left_out, shown in key_figures
             and the review stats;
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
             solid, current value boxed at its end), session-so-far (dashed); x = active minutes. The review page shows the same graph
             (review_data["live"], live rows up to the end + the end snapshot; [] for older sessions). Finishing
             the end snapshot runs compare and shows key_figures (net mesos/hr, EXP/hr, ...) right away.
quickslot.py Quick slot potions. find_panel: masked grey TM_SQDIFF of data/quickslot_panel.png (frame + gaps
             only; scripts/build_quickslot_template.py) in the bottom third, scaled by frame height. 2x4 slots
             (KEYS Shift..PgDn), counts via StackDigits (same font; a lone "0" only if cost < 0.2: "ATTACK"
             on Ctrl reads as 0 at 0.39). Verified on all 5 fixtures. Item: config quickslot.slots
             {key: name}, then <start>/quickslot.json from match_by_count (quick slot number = that item's
             inventory total in the start snapshot; exact count, ties broken by icon, else closest within 5;
             made at start finish, or from the first logged reading for older sessions; potion_series and
             the review apply it to logged rows by key), else itemdb.rescore (key-label rows + digits ignored) among use_candidates = the
             catalog's Use items (else all Use icons); a different name within 1.1x = unknown. The general
             identify() read Orange Potions as Brick and Lemons wrong on the real game (2026-11-01). Cached
             per key by 8x8 signature.
             POTIONS = NPC shop price + hp/mp (from memory: Red 50, Orange 160, White 320, Blue 200, Lemon 150 MP (Allen), Mana
             Elixir 620; config quickslot.prices overrides). Read at Start (first live.jsonl row, time = the
             start snapshot's) and with each live reading (row["potions"]). potion_series: drops between
             readings = used (net: gains count negative, so rates can go below 0), a reading outside its agreeing neighbours dropped; rates per
             kind like the EXP graph, current 5-min values boxed at the line ends in the GUI (raw_/ema_/cum_ hp|mp, mesos/hr). GUI draws HP/MP mesos/hr (dots, 5-min
             EMA solid, session dashed; y fits the lines) under the EXP graph, and quickslot.describe of the
             last reading under the timer ("Potions: Del Orange Potion 155 · ..."). Review page: same graph
             (review_data["potions"], prices from config quickslot.prices) ("Track potions" checkbox = SnapFlow.track_potions).
gamedata.py  EXP-to-next-level table (pre-Big-Bang values, levels 1-69).
config.py    Defaults + YAML merge. All reader boxes are [x, y, w, h] relative to capture.region.
```

## web/: browser prototype (2026-11-01)

Plain ES modules, no build step. Ports of the Python readers, checked to give the same results on every
fixture (`node web/test/run.mjs`: level, EXP, mesos, tab, tooltip slots, every stack number; item names
against a fake item DB cut from etc_excavation.png, compared with Python's read_page on the same data).

```
web/lib/img.js        mat {w,h,c,data Float32Array}, RGB. cvtColor grey, INTER_AREA/LINEAR/CUBIC resize, Otsu,
                      warpAffine-style resample, Laplacian sharpness, TM_CCOEFF_NORMED search (findScaled:
                      coarse on a shrunken copy, refined at full size, over candidate scales), masked TM_SQDIFF.
web/lib/ocr.js        Tesseract.js 5.1.1 (LSTM, best_int eng), from web/vendor/tesseract/ (committed), else jsDelivr.
web/lib/statusbar.js  statusbar.py: level tiles, EXP label (searched over scales; sets ctx.gameScale), resolve, meso field.
                      readCharacter (web only): class + name, the two white lines right of the LV tiles (tilesBox); grey OCR
                      at 4 sizes + soft threshold at 3; job snapped to JOBS, name = modal length + per-letter majority, then
                      snapped to a known character (ratio >= 0.8). Read at Start: session.character {name, job}, editable on
                      the control section (kv "char", "characters") and per session. Fixtures: Spearman/Swordsman, ImmovableObj.
web/lib/digits.js     digits.py (StackDigits, native view). Templates: data/stack_digits.json + web/local/digits.json.
web/lib/itemdb.js     itemdb.py rank/shortlist/rescore/identify; icons from web/local/itemdb.json.
web/lib/inventory.js  No calibration: locateInventory finds the "ITEM INVENTORY" title (web/data/inventory_title.png,
                      cut from etc_ant_tunnel.png); first slot = title + (3, 63) px at BASE_SCALE 1920/1366,
                      slot 44 px, pitch 36 x 34 native px (rows are closer than columns), 5 x 6 slots.
                      Items keyed by item-data id; LookCache (24x24 colour signature, mean abs diff <= 6) replaces
                      the catalog, re-checking named look-alikes + neighbours like _identify_slot.
web/lib/session.js    build_snapshot / compare / exp_gained / live_series equivalents. liveSeries uses plausibleRows: level progress
                      (level + exp/need) must rise; a reading above/below both neighbours is dropped, then any drop; the newest
                      is held back while > 4x the rate so far (a level misread at level-up spiked EXP/hr to millions). expBetween: level down = null.
web/lib/capture.js    getDisplayMedia (window), ImageCapture.grabFrame with video-element fallback, ticker in a
                      worker, stats (grabs while hidden, longest gap) to test background capture.
web/data/cursors.json Mouse-pointer templates (pointing + open glove, screen px at 1920/1366) from
                      scripts/build_cursor_templates.py (tests/fixtures/cursor_page.png, use_tab_tooltip.png).
                      inventory.findCursor: masked grey NCC over the grid, >= 0.8 rejects the page (no pointer
                      <= 0.64). Python app has no pointer check yet.
                      Meso field read on every page with its picture (snapshot.meso_pictures); when the total
                      changes during a scan (pet loot) End uses the first read, Start the last (mesos_changed).
                      snapshot.exp_picture = the EXP text as captured. Both shown in the review status table.
web/lib/mapname.js    mapname.py: minimap header (web/data/minimap_header.png) -> street/map lines, OCR variants,
                      snapped to web/local/maps.json (export_web_data.py) by a difflib-equal ratio(). Read at the
                      start of each scan, retried every 3 s on pages; missing -> "open the minimap (M)". Stored as
                      snapshot.map + map_picture, editable in the review (fixes.status[kind].map), leads the default name.
                      app.resnapMaps on every load: map.raw matched again against the current maps.json (key(): no case/punctuation),
                      saved sessions + current one updated, a default name starting with the old map follows; a typed map still wins.
web/lib/quickslot.js  quickslot.py: findPanel (coarse /4 search then refine, last position as hint), readQuickslot, matchByCount,
                      describe, potionSeries (seconds). app.js: read at Start (status frame) and with each live EXP reading
                      ("Track potions" checkbox, default web/local/quickslot.json enabled); names = config slots, then
                      matchByCount on the start inventory (session.qsNames), then icon among kv "useIds" (Use ids seen in
                      snapshots). Rows in session.potions [{time s, potions}]; graph (graph.js drawPotionGraph) in the view
                      and the pop-out, describe line under the live stats.
                      Swaps mid-run: keySig (6x6 mean colour, key label + digits masked) per key, baseline in session.qsSigs;
                      sigDiff > SIG_CHANGE 18 (same item same session <= 7, other items >= 24 on fixtures) = item changed ->
                      identify among potion-table Use items + useIds, qsNames[key] updated. Rows keep the name they were read
                      with and potPoints passes no keyNames, so the old potion's series stops and the new one's starts.
                      quickslot.trackKeys keeps names steady: a name told once is kept for the key (the 8x8 icon cache includes the
                      digits, so a later count could miss); a "changed" slot that can't be named and whose count didn't rise keeps
                      its name; Start merges icon names under matchByCount's. potionSeries fills unnamed saved rows the same way.
                      identify always searches the potion table's items too (an Orange Potion never seen in a snapshot wasn't in
                      useIds, so it could never be named); misses aren't cached (one miss used to stick for the page load); the
                      miss reason ("A or B?", "closest X, too different") shows in the describe line.
web/lib/liveinv.js    Live net mesos/hr from the inventory while grinding (checkbox "Live mesos from inventory", kv trackInv).
                      app.invTick polls every 2 s while running (not paused/scanning): inventory open + view still for one poll
                      + (view changed or 15 s since the last read: a stack count barely moves the signature) -> readPage + meso
                      field -> session.inv.reads [{t, tab, rows (liteRows, no pictures), mesos}] (kv invLive, record.inv, backup).
                      Tooltip/pointer over the grid: silently tried later. partStates: per part (Mesos = meso field, each tab the
                      Start scan read) its value over time; a tab = Start rows with each page written over the rows it shows at
                      alignPage's offset (ids only, counts break ties, empty slots neutral, <= 1/5 disagree, else skipped), valued
                      at priceOf. Quick slot potions are their own part "Potions" (-cumulative spend from potionSeries) and left
                      out of Use (skipNames). partPoints: rate = change since the part's previous point / active minutes between,
                      points >= 3 active min apart (reads come every 15 s; the inventory is still open right after the Start
                      scan, which once made a huge frozen negative), and a pause in between restarts from the first state after
                      it (selling Etc / repotting while paused counted as income, 2026-11-10). potionSeries skips count changes
                      across a pause too. liveNet: net now = every part at its newest rate (an outdated part keeps its last
                      rate), session = sum of per-part gain / minutes covered; total = net after each point. Shown: liveStats row
                      (now · session), #invLine (each part's rate + age), graph.drawLines (one line per part, thick Net, a line
                      ends where its part was last read) in the view (#invGraph) and the pop-out (canvas ig); review compares
                      with the End result. fixes.looks apply.
web/graph.js          Canvas graphs (drawGraph EXP, drawPotionGraph, drawLines inventory parts). Time window cv._view {w, end}:
                      a running session's graphs show the last LIVE_W = 60 active min, following now; ended sessions show all.
                      Wheel = zoom around the pointer, drag = pan (panned back = stops following), double-click = reset. y range
                      fits the visible points only; the last visible point is labelled. Reset per shown session (S.graphFor).
web/panels.js         makePanels: Results / EXP/hr / Potion cost / Live mesos/hr / Review each in a panel with a title bar
                      (drag handle, up/down, collapse). Order + collapsed in localStorage grindcap.panels. A panel hides when its
                      element is hidden or empty; expanding redraws its canvases (cv._redraw).
web/lib/store.js      IndexedDB (db "grindcap"): kv store (current session's start/end/live/pauses/fixes/name,
                      corrections, "sessions" = light index) kept in memory + written through; "sessions" store =
                      one record per ended session {id = start time, name, start, end, fixes, live, pauses, result}.
                      Moves old localStorage keys over once; asks navigator.storage.persist().
web/app.js            Page = big control section (Share, Start/End/Pause/Discard, character, timer, tab chips, live EXP/hr,
                      "Your data": Back up all data = one grindcap-backup JSON {sessions (full records), kv}; Restore merges
                      (new ids added, newer `saved` replaces, corrections/characters unioned, running session only if none here))
                      + tabs "Session review" (the viewed session) | "Summary" (table of saved sessions: character + map filters, Level start→end, click a header to sort, kv "sumSort"; light index has map/level from record.meta = fixed values, store.reindex backfills;
                      Allen will add more there). Session review = the viewed session (‹ › paging, rename, delete, results, EXP/hr graph, review). S.cur = running
                      session (same object as its saved record once ended), S.view = shown one. Pop-out opens on
                      Share/Start (Document PiP needs a click), "Re-open pop-out" when closed. UI, one session like gui.py: Start (status + pages) -> live EXP every N s while running ->
                      End (status + pages) -> compare. Pause/Resume (S.pauses [[t0,t1|null]], left out of compare
                      minutes and liveSeries x/rates), Discard. Pages auto-captured (PageWatcher), auto-finish when
                      Equip/Use/Setup/Etc seen + 4 s idle. Page tab = inventory.pageTab: items decide, but a Cash/Deco button wins unless 70% of filled slots agree (cash items are not in the item data and false-match). Start/end snapshots, live rows, pauses in localStorage.
web/lib/stats.js      Stat window (S), optional ("Read stat window" checkbox, kv readStats, default on). No template of the real window
                      yet: ocrWords (psm 11, word boxes, own Tesseract worker "stats" so it runs beside the page reads) on the whole
                      frame finds STR/DEX/INT/LUK stacked in one column (3 of 4), then the area around it is read again at 3x;
                      parseWords splits each line into LABEL value fields by label name (FIELDS: level, exp, hp/mp cur/max,
                      ap, fame, str/dex/int/luk total (base+bonus), attack min~max, wdef, magic, mdef, accuracy, avoid, hands,
                      speed, jump), so layout doesn't matter. ok = all 4 main stats read and every base+bonus adds up.
                      app.tryStats: during Start/End scans every 6 s, max 10 tries, not awaited (~3-6 s per try); auto-finish waits
                      for one under way. Saved as snapshot.stats {values, lines, ok, why, box, picture}; fixes.status[kind].stats
                      {field: n}; withFixes -> statValues (stats.flat + fixes); record meta.stats (start, else end) for the Summary.
                      Review: "Character stats" table (start/end inputs, base+bonus shown) + the window pictures. Tested only on a
                      synthetic window drawn over game_frame.png (web/test/stats_test.js; PAGE=stats_only.html node web/test/run.mjs
                      runs just that). Python app: no stat window.
                      2026-11-11 (Allen: "scan this at any time, don't need before and after"): one reading per SESSION (session.stats,
                      kv sessStats, record.stats, backup): app.bgStats every 30 s while running (2 min once a reading adds up), the
                      "Read stats" button any time (running session, else the one shown), Start/End scan reads feed it too (keepStats:
                      ok beats not-ok, newer ok wins, else more fields). Fixes: fixes.stats; meta.stats = sessionStats first. The
                      review shows one column (older sessions with only start/end reads keep those columns).
web/lib/tags.js       Session tags (user-made): kv "tagList" = your tags in order (case-insensitive, first spelling kept), record.tags
                      (running session: kv "sessTags"), in the light index and the backup. Review: chips with × + "+ add tag" box
                      (datalist; a new name makes the tag). Summary: Tags column + Tag filter (incl. "(no tags)"), "Your tags" manager
                      (count, ✎ rename / × delete everywhere: app.retag), row selection = drag over rows (from a selected row unselects),
                      shift-click range, box/ctrl-click toggle, plain click opens unless something is selected; sticky bar adds/removes
                      a tag on all selected (app.tagSessions). Python review.html has no tags.
web/scatter.js        "Scatter" tab next to Summary: one SVG dot per saved session (light index), x = EXP/hr, y = Net / Revenue /
                      Mesos per hr (select), axes fitted to the data. Colour by (kv scatterOpt): map / character / class / first tag
                      (in your tag-list order) = categorical, dataviz palette in fixed order by session count (8 slots + shapes,
                      rest grey "Other"), legend chips hide/show (not persisted); level / minutes / date = sequential blue ramp.
                      Hover tooltip, click opens the session. Re-rendered from renderSummary when the tab is open.
web/review.js         Review panel: status inputs + meso field crop, price input per item row (kv "myPrices", global: wins over
                      item-data/catalog/NPC price; app.setPrice recomputes the shown session at once, all saved ones after 0.8 s), "Not recognised" cards (slot picture, why, 6 closest
                      item-data guesses as buttons, name search, Don't count), items table with how each was named and
                      per-slot pictures/count fixes, captured page pictures. Fixes {looks, qty, status} -> session.withFixes.
web/popout.js         Always-on-top Document Picture-in-Picture window (Chrome/Edge 116+): sharing state, timer, EXP/hr, Compact/Full view button = small mode
                      (timer, EXP/hr + %/hr, current HP/MP mesos/hr; sized to its content by fitSmall (resize needs a click: re-fit on pointerup; size remembered in grindcap.popSmallSize); scan line with the tabs still to do while scanning; localStorage grindcap.popSmall),
                      (5-min EMA), graph (web/graph.js), Start/End/Finish/Live, tab checklist + finish countdown, result.
                      Corrections: naming a look on the review panel (learn() in app.js) is kept in localStorage
                      "corrections" ({sig 24x24, id|'ignore', name, how, crop}), seeded into LookCache on load (a corrected
                      look wins within threshold/2; up to the full threshold it wins unless identify() clearly names another item, since
                      the item data's icon can be unlike the game's: Skeledog's Bone read as Diamond vs Broken Mirror Glass 1.03x), "Download my corrections" exports them.
scripts/export_web_data.py  <catalog_dir>/itemdb + catalog prices + digits.npz -> web/local/ (gitignored).
                      Items without an icon (maplestory.io /icon errors, e.g. Skeledog's Bone 4000154) are exported too: name
                      search only, never auto-matched; a look you name as one wins within the full LookCache threshold.
                      ItemDB.fetch_icon: /icon, else the item JSON's metaInfo.icon (base64; /icon errors on 4000154 but the JSON has it),
                      else the same name in GMS v83, else cdn.meowdb.com. export_web_data runs ItemDB.download first (whole category per request: the paged list had skipped 4000154; existing
                      entries kept) then fills missing icons (--no-icons skips). Review name search ignores case/punctuation, accepts a unique part.
                      NPC prices: ItemDB.price was only fetched for items the Python app identified, so most items had none;
                      export_web_data.fetch_prices fetches every missing one (8 threads, saved to items.json, --no-prices skips); no MCW price (equips,
                      e.g. Brown Piettra 1041069: meowdb says 7,000) -> same id in GMS v83, asked once (price_gms).
                      app.fillPrices asks maplestory.io in the browser for items in the shown session still without one (kv npcPrices).
scripts/export_web_backup.py  grindcap-gui sessions (sessions.list_sessions + load_snapshot, fixes applied, ids no longer in
                      the catalog dropped like compare) -> a grindcap-backup file for Restore: items keyed by catalog db id
                      (else "gui:item-NNN" with the catalog price in kv "prices"), sessions.json name/map, pauses, checked
                      live rows, potion rows + quickslot.json, page PNGs cropped to the slots as JPEG, --character/--job.
                      Restore computes the missing result with the web compare (matched Python on a synthetic session).
scripts/serve_web.py  localhost:8765 with explicit JS MIME types (Windows registry can make .js text/plain).
```

Allen's local teaching (data/catalog.json names/prices, icons/ looks, data/digits.npz, all gitignored) must
become the hosted version's starting data; he must never re-teach. Planned: tooltip-hover naming of unknown icons.

Not yet tested on the real game in a browser: covered window, background tab, windowed mode (title bar in
the frame), other resolutions. Unrecognised items get "look-N" ids that only line up within one page load.

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
