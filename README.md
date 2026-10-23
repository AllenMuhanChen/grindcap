# grindcap

Measures your MapleStory Classic grinding sessions by watching the screen. It reads your HP, MP, EXP and meso total a few times a second and turns the changes into events:

| What changes | Event |
|---|---|
| HP goes down | a monster touched you (and for how much) |
| HP goes up | regen, a potion, or a Final Attack heal |
| MP goes down by a skill's cost | you cast that skill |
| MP goes up | regen or a potion |
| EXP goes up | a kill (split into several when the gain is a multiple of the monster's EXP) |
| Meso total goes up | mesos picked up |

From those it works out the numbers Grind Ledger needs you to fill in by hand: **touches per kill**, **seconds between kills**, **mesos per kill**, plus EXP/hr, casts per kill and potion use.

It only reads the screen. It never sends keys or clicks to the game.

## Quick start: the control window

```
pip install -e ".[ocr,dev]"
grindcap-gui
```

A small window opens and stays on top of everything. It captures the MapleStory window directly, even when other windows cover it (the game just can't be minimized).

1. Click **Start snapshot**. It reads your EXP and mesos right away and shows them, so you can check.
2. In the game, open your inventory and scroll through every tab, top to bottom. Pages are captured automatically each time you stop scrolling. You can also press **F8** to capture a page by hand.
3. Click **Finish** (or press **F10**).
4. Grind. Then do the same with **End snapshot**.
5. Click **Compare** to see EXP/hr, mesos/hr and items gained or used, plus a report with item icons.

Check the capture works with `grindcap test-capture`: it saves `captures/test_capture.png` and says which method it used. If your game's window title doesn't contain "MapleStory", run `grindcap windows` and set `capture.window_title` in `config.yaml`.

## Two ways to use it

- **Before/after snapshots (start here).** Take a snapshot of your EXP, mesos and whole inventory, grind, take another, compare. Gives EXP/hr, mesos/hr, and every item gained or used per hour (potions drunk show as negative). No live tracking needed.
- **Live tracking.** Watches HP/MP/EXP continuously to count touches, casts and kills.

## Setup (Windows)

1. Install Python 3.10 or newer.
2. In this folder:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -e .[ocr,dev]
   ```
3. Install Tesseract OCR (for reading the EXP and meso numbers): https://github.com/UB-Mannheim/tesseract/wiki. If it isn't on your PATH, set `session.tesseract_cmd` in `config.yaml`.
4. Copy `config.example.yaml` to `config.yaml` and set your level, skill MP costs and the monster you're farming.

## Calibrate

Open the game in windowed mode with your inventory window open (so the meso total is visible), then:

```
grindcap calibrate
```

A screenshot opens, shrunk to fit your screen. For each of HP, MP, EXP and mesos: drag roughly around it and press Enter, then it zooms in and you drag tightly around it and press Enter again. Press C to skip one. For the HP and MP bars, do this when they're fairly full: the tool samples the bar colour from the left part of the box.

Check it:

```
grindcap snapshot     # saves the screenshot, the boxes drawn on it, and each crop to captures/
grindcap watch        # prints live readings; take a hit, cast a skill and watch the numbers move
```

You can calibrate on a saved screenshot or a recording instead of the live screen: `grindcap calibrate --image shot.png` or `grindcap calibrate --video grind.mp4 --at 12`.

## Before/after snapshots

One-time setup, with your inventory window open:

```
grindcap calibrate --only exp mesos level inventory
grindcap teach-digits      # optional check of the stack numbers
```

`calibrate` asks for boxes around your EXP number, meso total and level, then the top-left and bottom-right visible inventory slots. It also asks for two anchors: the inventory window's title bar and a fixed label on the status bar. Those let it find the inventory and the status bar wherever they are on screen, so you can move the inventory or the game window freely between snapshots.

Stack numbers are read with templates of the game's own digit font, which come with grindcap (cut from a real screenshot), so there is nothing to teach. `teach-digits` is a check: it reads every stack number in your open inventory, shows a picture with what it read under each slot (also saved as `captures/slots/readings.png`), and asks you to press Enter if all are right or type fixes like `r1c4=59`. Whatever you confirm or fix is added to its examples. If the numbers are in the wrong slots, the grid is off: run `grindcap calibrate --only inventory` and check the column and row counts.

Each grind:

```
grindcap snap start
```

It grabs EXP and mesos, then, in game:

- **F8:** capture the visible inventory page. Scroll down and press F8 again, until the end of the tab. Overlapping rows are merged automatically.
- **F9:** move to the next tab (Equip, Use, Etc, Setup).
- **F10:** done.

Grind, then:

```
grindcap snap end
grindcap compare
```

`compare` prints EXP/hr, mesos/hr and an item table, and writes `report.html` with each item's icon. Items are recognised by icon, so new ones show as `item-001`, `item-002`. Name and price them once:

```
grindcap items
grindcap label item-001 --name "Green Mushroom Cap" --price 14
```

If you took a break between snapshots, pass the real grinding time: `grindcap compare --minutes 45`.

Pages are stitched together so every slot counts once: scroll overlap is matched by item icons, and a view captured twice (or a tab visited again) is skipped, even if one slot looks different because of the cursor. Each snapshot folder keeps its screenshots, so after an update `grindcap reread` reads the latest start and end snapshots again, and `grindcap compare` then uses the new readings.

## Track a session

```
grindcap run
```

Grind normally. Events print as they happen and are logged to `sessions/<time>_<monster>.jsonl`. Press Ctrl+C to stop and print the summary.

Or record your screen (OBS, Xbox Game Bar) and run it afterwards:

```
grindcap replay grind.mp4
```

## Results

```
grindcap summarize sessions/20261022-210000_Green_Mushroom.jsonl
grindcap export sessions/20261022-210000_Green_Mushroom.jsonl
```

`export` prints the values to enter in Grind Ledger's monster editor: touches per kill, seconds between kills and mesos dropped per kill.

## Known limits

- **HP and MP bars are pixel-accurate, not point-accurate.** A 200 px bar on a 1,000 HP character resolves 5 HP. Switch HP/MP to `mode: text` to read the numbers instead.
- **Live tracking doesn't count item drops**, only floor mesos. Use before/after snapshots for items.
- **Snapshots:** don't hover over items while capturing, since tooltips cover slots.
- **Stack numbers** are matched in the game's own pixels: the game draws at a lower resolution (e.g. 1366x768) and stretches it to the window, and grindcap undoes the stretch using the slot spacing. It was built on one 1920x1080 screenshot; if your window size gives wrong numbers, `teach-digits` with corrections fixes it.
- **Regen vs potions is guessed by size.** Tune `hp_regen_max` and `mp_regen_max` to your character.
- **Kill counting needs the EXP number visible** (or the EXP bar in `mode: bar`, which is too coarse at higher levels).
