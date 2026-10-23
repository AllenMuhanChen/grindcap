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

A screenshot opens. For each of HP, MP, EXP and mesos, drag a box around it and press Enter (press C to skip one). For the HP and MP bars, do this when they're fairly full: the tool samples the bar colour from the left part of the box.

Check it:

```
grindcap snapshot     # saves the screenshot, the boxes drawn on it, and each crop to captures/
grindcap watch        # prints live readings; take a hit, cast a skill and watch the numbers move
```

You can calibrate on a saved screenshot or a recording instead of the live screen: `grindcap calibrate --image shot.png` or `grindcap calibrate --video grind.mp4 --at 12`.

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
- **Item drops aren't counted yet**, only floor mesos. Reading the pickup messages is the next step (see CLAUDE.md).
- **Regen vs potions is guessed by size.** Tune `hp_regen_max` and `mp_regen_max` to your character.
- **Kill counting needs the EXP number visible** (or the EXP bar in `mode: bar`, which is too coarse at higher levels).
