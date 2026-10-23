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
digits.py    DigitReader: stack numbers by template matching on the game's fixed font (taught via
             `teach-digits`), with splitting of touching glyphs. Tesseract is the fallback.
snapshot.py  Before/after mode: build_snapshot, compare (EXP across level-ups, mesos, item deltas/hr,
             value from catalog prices), text + HTML report, PageCollector (F8/F9/F10 via pynput).
cli.py       calibrate | snapshot | watch | run | replay | summarize | export |
             snap start/end | compare | items | label | teach-digits
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
captures, different items must not), empty-slot detection threshold, the stack-number colour (the
teach step tries white then black), and whether hover highlights change icons.

The user's preferred first workflow is snapshots (start/end), not live tracking.

## Next steps

- Item drops: OCR the pickup messages in the chat/system log ("You have gained an item ...") and count by item, so drop rates can replace the OSMLib reference rates.
- Separate "touches" from fall damage and skill HP costs (Slash Blast costs HP).
- Attribute kills to monsters by EXP value when a map has several monster types.
- Write `ledger_export` output in a format Grind Ledger can import directly.
