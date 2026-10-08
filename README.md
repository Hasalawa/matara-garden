# Matara Garden

A weekly garden checklist for home gardeners in Matara, Sri Lanka. Open it, see what to harvest, sow and look after this week, and tick things off as you do them outside. The screen is the shortest part of the day.

It runs on your own laptop, offline. A small rule-based crop calendar decides what needs doing (so dates and crops are never made up), and a local open-weight model, Gemma through Ollama, writes the short weekly note at the top.

## Run it

1. Install [Python](https://www.python.org/downloads/) (tick "Add python.exe to PATH") and [Ollama](https://ollama.com).
2. Download the model once: `ollama pull gemma3`
3. In this folder run: `python server.py` (on Windows you can also double-click `start.bat`)

Your browser opens at http://localhost:8000. To open it on your phone, run `python server.py --host 0.0.0.0` and visit `http://<your-laptop-ip>:8000` on the same Wi-Fi.

No packages to install: the app uses only Python's standard library. If Ollama isn't running, the checklist still works and the note shows a message.

## Using it

- **Harvest**: crops in My garden that are ready within a week. Tick when picked.
- **Sow and plant**: crops that suit this month's rain. Ticking one adds it to My garden with today's date, so the app can tell you when it is ready.
- **Care**: jobs for this month's rain level (drains, staking, mulch). Ticks reset each week.
- **My garden**: add what you already have growing, remove mistakes, and set sunlight and garden size.
- **EN / සිං**: switch the weekly note between English and Sinhala.

Everything is saved in `garden.json` on your machine.

## Options

```
python server.py --model gemma3 --port 8000
python planner.py --no-ai        # text version in the terminal
python planner.py --date 2026-01-20 --lang si
```

Add `?date=2026-01-20` to the web address to preview another week.

## Crop data

`crops.json` is starter data written from general knowledge for the southern wet zone. Check sowing windows with your local Agrarian Service Centre or the Department of Agriculture, and edit the file to match what works in your soil.

## Why open-source AI here

- It runs with no internet, which matters in a garden with weak signal.
- Garden and location data never leave your laptop.
- The model is swappable with `--model`, and the rules keep it honest: it only rewrites facts it is given.
