# Fanzhuan Waiyu Automation Assistant (AutoSwapEng-Next)

English | [中文](README.md)

An automation helper for the **Fanzhuan Waiyu** ("Flipped Foreign Language") vocabulary mini-program, built with **screen mirroring + PaddleOCR + PyAutoGUI**. It supports multiple-choice, spelling, handwriting and listening exercises.

> This project is based on the ideas and initial implementation of [**ZRedTea/AutoSwapEng**](https://github.com/ZRedTea/AutoSwapEng) (MIT License).
> This repository is a **complete rewrite**: window capture, OCR parsing, answer decision, handwriting strokes and error handling were rebuilt from scratch, with added OPPO Connect (OPPO 互联) screen-mirroring support.
> The original project is copyright **ZRedTea**. This project is not affiliated with the original author.

## Features

- **Automatic exercise detection**: multiple choice, meaning-to-word spelling, handwriting pad, listening, study cards
- **Automatic pack-stage detection**: study cards / quiz / post-mistake reinforcement; enters reinforcement automatically after the study summary
- **Multiple choice**: scores options using a local vocabulary, ECDICT and online dictionaries; detects red/green answer feedback and retries with the next option when wrong
- **Spelling**: reverse lookup from Chinese meaning to English candidates, taps the on-screen keyboard, retries alternative candidates on failure
- **Handwriting**: built-in single-stroke alphabet; draws the word on the writing pad via PyAutoGUI. Supports whole-word, letter-by-letter and one-letter-per-box modes
- **Mirroring support**: auto-detects portrait mirror windows from OPPO Connect / O+ Connect / Cross-Device Connect / scrcpy
- **Safety guards**: refuses desktop/landscape targets, detects black frames, and supports a mouse-to-corner emergency stop
- **Diagnostics**: crashes are written to `logs/crash.log`; `doctor.bat` generates an environment/screenshot/OCR report

## Differences from the original project

| | Original AutoSwapEng | This repository |
|---|---|---|
| Window targeting | Manually recorded coordinates | Auto-detects mirror windows, also supports drag selection |
| Capture | pyscreenshot | mss with DPI awareness |
| OCR | PaddleOCR | PaddleOCR 2.9.1, zoomed re-OCR and annotated debug images |
| Exercise types | Choice / spelling / listening | Choice / spelling / handwriting / listening / study cards |
| Answering | Fuzzy string matching | Local vocabulary + ECDICT + reverse lookup + online dictionaries + learned cache |
| Handwriting | None | Single-stroke alphabet + PyAutoGUI drawing |
| Robustness | Coordinate/fixed-ratio dependent | OCR-element based, debounce, emergency stop, crash log, diagnostics |
| Mirroring | Generic screen coordinates | OPPO Connect window detection, black-frame and wrong-target guards |

## Requirements

- Windows 10 / 11
- A phone-mirroring app on the PC (recommended: **OPPO Connect → Phone Screencast**, or scrcpy / Escrcpy)
- The Fanzhuan Waiyu mini-program must be visible and usable in the mirror window
- The first installation downloads Python 3.12, PaddlePaddle, PaddleOCR and Chinese OCR models (about 500–800 MB)

## Installation

Double-click **`install.bat`**. It will:

1. Check or install Python 3.12
2. Create the `.venv` virtual environment
3. Install PaddleOCR, PyAutoGUI, mss and other dependencies
4. Download the Chinese OCR model on first OCR run (about 20 MB)

Manual installation:

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## Usage

1. Open OPPO Connect's "Phone Screencast" so the Fanzhuan Waiyu screen is visible
2. Double-click **`run.bat`**
3. On first use, choose `1`:
   - Press Enter: auto-detect the mirror window
   - Or press `d`: drag-select **only the phone screen** (exclude toolbars and black borders)
4. Choose `3` to capture a frame and run OCR diagnostics
5. Choose `2` to start

The program automatically recognises whether it is in the **study-card / quiz / reinforcement** stage and clicks "进入强化" (Enter reinforcement) on the study summary page.

Listening dialogues: the flow clicks the **left speaker once**, then hammers the **bottom-right arrow**. Each round is 50 clicks and every click compares the question area, stopping as soon as the next listening screen appears; if a round finishes without any progress change it keeps clicking in the next round (8 rounds max by default). The right waveform only replays your own recording and the center microphone records; neither is clicked. If positions are off, run `setup` step 5 and calibrate only the play and bottom-right arrow positions.

Common commands:

```bat
run.bat setup                  :: re-select the window / calibrate keyboard and handwriting area
run.bat run --dry-run          :: recognize only, never click
run.bat run --mode spell       :: spelling exercises only
run.bat ocr --image captures\live.png   :: run OCR on an existing screenshot
run.bat doctor                 :: generate a diagnostic report
```

Move the mouse to the top-left corner of the screen to trigger the emergency stop.

## OPPO Connect notes

- Auto-detects **portrait** windows whose titles contain `OPPO`, `O+ Connect`, `互联`, `跨屏`, `投屏`, `手机投屏`, `OnePlus`, `一加`, `realme`, etc.
- The landscape control panel of OPPO Connect is never selected
- If the mirror window title does not contain those keywords:
  - Run `setup` and pick the window marked `★` or `△` by aspect ratio
  - Or press `d` and drag-select the phone area
- If the captured frame is black: disable "HD quality / hardware acceleration / privacy protection" in OPPO Connect, or switch to scrcpy
- If the window has a toolbar or sidebar, select only the phone screen for more accurate clicks and swipes

## Dictionary (bundled)

The release includes an English-Chinese vocabulary generated from **ECDICT**: `data/vocab.json.gz`, about **106k words / 300k senses**, ~12 MB uncompressed, redistributed under ECDICT's MIT license (see `data/LICENSE-ECDICT.txt`). A local `cache/vocab.json` takes precedence.

Meanings are resolved in this order:

1. Local `cache/vocab.json` (CET4/CET6/high-school + ECDICT, generated by `tools/build_vocab.py`)
2. `data/vocab.json.gz` (bundled ECDICT vocabulary)
3. **ECDICT** offline dictionary (optional, broader coverage)
4. Youdao / Bing online dictionaries (network required)

### Configure ECDICT

1. Download `ecdict-sqlite-28.zip` from [ECDICT Releases](https://github.com/skywind3000/ECDICT/releases) and extract `stardict.db`
2. Put `stardict.db` under `ecdict\`, or set an absolute path in `config.json`:

```json
"solver": {
  "ecdict": "D:/dict/stardict.db",
  "online": true
}
```

The program still works without ECDICT, but choices and spelling candidates rely more on online dictionaries.

### Build the local vocabulary (optional)

Prepare CET4/CET6/high-school word lists in JSONL (`CET4_3.json`, `CET6_3.json`, `GaoZhong_2.json`) and place them at:

```
vocab_tmp/cet4/CET4_3.json
vocab_tmp/cet6/CET6_3.json
vocab_tmp/gaozhong/GaoZhong_2.json
```

Then run:

```bat
set ECDICT_DB=D:\dict\stardict.db
python tools\build_vocab.py --out cache\vocab.json
python tools\verify_vocab.py --vocab cache\vocab.json
```

Build a redistributable vocabulary from ECDICT only:

```bat
python tools\build_vocab.py --ecdict-only --out data\vocab.json
```

`tools/verify_vocab.py` checks structure, known words (bridge/intense/built/caught/chosen, etc.) and samples ECDICT for consistency; the report goes to `logs/vocab-report.txt`.

Merge validated meanings from local study records (`cache/study.json`, `cache/learned.json`) into the local vocabulary:

```bat
python tools\merge_app_cache.py
```

The script filters OCR mistakes and concatenated fragments (e.g. `agree -> 同思`, `顾客主顾`), and writes a report to `logs/vocab-merge-report.txt`.

## Configuration

`setup` generates `config.json`, which is ignored by Git. Common fields:

| Field | Description |
|---|---|
| `window_title` | Mirror window title fragment; leave empty for auto-detection |
| `bbox` | Capture region `[x1, y1, x2, y2]` in physical screen pixels |
| `keyboard.bbox` | On-screen keyboard region for spelling (calibratable) |
| `spell_input` | Click position of the spelling input box `[x, y]` |
| `listen.play` / `listen.next` | Screen coordinates of the play speaker and bottom-right submit/next arrow (`setup` step 5) |
| `listen.auto_flow` | `true`: play once then click the arrow repeatedly; `false`: play only, default `true` |
| `listen.play_wait` | Seconds to wait after playing, default 2.0 |
| `listen.arrow_clicks` / `listen.arrow_interval` | Clicks per round / interval, default 50 / 0.2 s |
| `listen.arrow_rounds` | Extra rounds when progress does not change, default 8 |
| `listen.stop_on_change` | Stop clicking as soon as the next screen appears, default `true` |
| `auto_enter_reinforce` | Enter reinforcement automatically after the study summary, default `true` |
| `pack_memory` | Remember pack words and mistakes between runs, default `true` |
| `write_canvas` | Handwriting pad region `[x1, y1, x2, y2]` |
| `handwriting.mode` | `word` for continuous writing, `letter` for letter-by-letter |
| `handwriting.letter_boxes` | If greater than 1, split the pad into N boxes, one letter per box |
| `type_method` | `tap` to tap the on-screen keyboard, `type` to type with the PC keyboard |
| `solver.ecdict` | Path to the ECDICT database |
| `ocr.min_score` | OCR confidence threshold |

See [`config.example.json`](config.example.json).

## FAQ

**The window closes immediately**

- Start with `run.bat`, not by double-clicking `main.py` (although `main.py` does switch to `.venv` automatically)
- Check `logs\crash.log`
- Run `doctor.bat` and attach `logs\doctor.txt` to an issue

**Black capture**

- Disable "HD quality / hardware acceleration / privacy protection" in OPPO Connect
- Or switch to scrcpy / Escrcpy

**Mirror window not found**

- Open OPPO Connect's "Phone Screencast" before starting
- In `setup`, press `d` and drag-select the phone screen

**Handwriting is not recognized**

- Preview the strokes with `run.bat preview --word hello`
- If the pad uses one box per letter, set `handwriting.letter_boxes` to the number of boxes
- Adjust `write_canvas` to cover only the writable area

**Wrong spelling input position**

- Re-run step 4 of `setup` and record the input box position with the mouse
- Or set `type_method` to `"type"` to type directly

**Wrong listening click position**

- Dialogue page: left speaker (play), center microphone (record), right waveform (replay your recording), bottom-right arrow (submit + next)
- The flow only clicks the left speaker once and the bottom-right arrow (50 clicks per round); it keeps going when progress does not change and stops as soon as the next screen appears
- Defaults use screenshot-derived ratios; if the mirror window has a title bar or scaling, run `setup` step 5 and calibrate play + arrow
- Calibrated coordinates are only valid while the window stays in place
- Tune `listen.arrow_clicks` / `listen.arrow_interval` / `listen.arrow_rounds` to change count, interval or rounds
- If a toast causes a false stop, set `listen.stop_on_change` to `false`
- To play without auto-advancing, set `listen.auto_flow` to `false`
- The window now stays open after a normal run; if it still closes instantly, check `logs/crash.log` and run `doctor.bat`

**Reviewing mistakes / OCR errors**

- Every run writes a record to `logs/answers-*.jsonl`
- Each line contains pack, stage, progress, OCR word, options, actual click and feedback; attach it to an issue if needed

## Project structure

```
main.py              CLI entry point / interactive menu
fzauto/
  screen.py          window detection, capture, black-frame checks
  ocr.py             PaddleOCR wrapper and annotated debug images
  ui.py              UI element parsing and exercise-state detection
  words.py           vocabulary, ECDICT, online dictionaries, reverse lookup
  solver.py          multiple-choice scoring and spelling candidates
  strokes.py         single-stroke alphabet
  actions.py         clicks, swipes, keyboard input, handwriting
  session.py         pack-stage detection, studied words and mistakes
  runner.py          main loop
tools/
  build_vocab.py     local vocabulary builder
  verify_vocab.py    vocabulary structure/consistency checks
  merge_app_cache.py merge validated meanings from local study records
  sim_cases.json     offline multiple-choice test cases
data/
  vocab.json.gz      bundled ECDICT vocabulary
  vocab-meta.json    vocabulary version/counts/checksum
  LICENSE-ECDICT.txt ECDICT MIT license
install.bat/.ps1     installation scripts
run.bat              launcher
doctor.bat           diagnostics
```

## Disclaimer

- This project is for **personal study assistance and technical research only**. Follow the terms of Fanzhuan Waiyu, your school and any related services.
- Do not use it for ghostwriting, cheating or any other prohibited purpose. Use at your own risk.
- The program does not collect or upload account information; screenshots, logs and vocabulary caches stay on your machine.
- Third-party dictionaries (ECDICT, etc.) are governed by their own licenses.

## License and credits

Licensed under the [MIT License](LICENSE).

- Original project: [ZRedTea/AutoSwapEng](https://github.com/ZRedTea/AutoSwapEng) — idea and initial implementation
- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) — text recognition
- [ECDICT](https://github.com/skywind3000/ECDICT) — offline English-Chinese dictionary
- [PyAutoGUI](https://github.com/asweigart/pyautogui), [mss](https://github.com/BoboTiG/python-mss), [PyGetWindow](https://github.com/asweigart/pygetwindow)
