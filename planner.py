#!/usr/bin/env python3
"""Matara Garden Planner: core logic.

Rules decide WHAT to do this week (sowing windows, harvest dates, rain care),
so dates and crops are never made up. A local open-weight model (Gemma via
Ollama) only writes the short friendly note on top.

Run `python server.py` for the web app, or `python planner.py` for a text version.
"""
import argparse
import json
import re
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent

CARE = {
    1: [
        ("water", "Water early in the morning, before the sun gets hot"),
        ("mulch", "Spread dry leaves or straw around the beds to hold moisture"),
        ("wilt", "Check young seedlings for wilting in the afternoon"),
    ],
    2: [
        ("soil", "Push a finger into the soil and water only if the top 2 cm is dry"),
        ("weed", "Pull weeds while the soil is soft"),
        ("pests", "Check leaves for holes and pests"),
    ],
    3: [
        ("drain", "Check that rain water drains away from your beds"),
        ("stakes", "Tie up or stake climbers and tall plants"),
        ("leaves", "Look for leaf spots or mould and remove affected leaves"),
    ],
    4: [
        ("drains", "Clear the drains and channels around the garden"),
        ("cover", "Move seedlings to raised beds or under cover"),
        ("leafy", "Harvest leafy greens before heavy rain"),
        ("mould", "Remove yellow or mouldy leaves"),
    ],
}


# ---------- files ----------

def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path, obj):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


# ---------- plan ----------

def week_start(d):
    return d - timedelta(days=d.weekday())


def _ready_text(days_left):
    if days_left < 0:
        n = -days_left
        return f"Overdue by {n} day{'s' if n != 1 else ''}"
    if days_left == 0:
        return "Ready today"
    return f"Ready in {days_left} day{'s' if days_left != 1 else ''}"


def build_plan(today, garden, data):
    month = today.month
    rain = data["rainfall_level"][str(month)]
    sun = garden.get("sun", "full")
    crops = {c["id"]: c for c in data["crops"]}
    ws = week_start(today)
    wk = ws.isoformat()
    planted = garden.get("planted", [])
    checks = garden.get("checks", {})

    harvest, rows = [], []
    for p in planted:
        c = crops.get(p["crop"])
        if not c:
            continue
        start = date.fromisoformat(p["date"])
        ready = start + timedelta(days=c["days_to_harvest"])
        days_left = (ready - today).days
        pct = max(0, min(100, round(100 * (today - start).days / c["days_to_harvest"])))
        key = f'{p["crop"]}@{p["date"]}'
        harvested = p.get("harvested")
        rows.append({
            "key": key, "crop": p["crop"], "title": c["name_en"], "local": c["name_si"],
            "planted": p["date"], "ready": ready.isoformat(), "days_left": days_left,
            "pct": 100 if harvested else pct, "harvested": harvested,
        })
        item = {
            "id": f"harvest:{key}", "title": c["name_en"], "local": c["name_si"],
            "detail": f"{_ready_text(days_left)}, planted {p['date']}",
            "overdue": days_left < 0, "done": bool(harvested),
        }
        if harvested:
            if harvested >= wk:
                harvest.append(item)
        elif days_left <= 7:
            harvest.append(item)

    sow, hold = [], []
    for c in data["crops"]:
        if month not in c["sow_months"]:
            continue
        if sun == "partial" and c["sun_need"] == "full":
            continue
        if rain == 4 and c["rain_tolerance"] == "low":
            hold.append(c["name_en"])
            continue
        mine = [p for p in planted if p["crop"] == c["id"]]
        sow.append({
            "id": f"sow:{c['id']}", "title": c["name_en"], "local": c["name_si"],
            "detail": f"{c['method']}, {c['spacing_cm']} cm apart, ready in about {c['days_to_harvest']} days",
            "tip": c["tip"],
            "caution": "Rain-sensitive: use a raised bed or cover" if rain == 3 and c["rain_tolerance"] == "low" else None,
            "growing": any(not p.get("harvested") and p["date"] < wk for p in mine),
            "done": any(p["date"] >= wk for p in mine),
        })

    care = [{"id": f"care:{cid}", "title": text, "done": bool(checks.get(f"{wk}:{cid}"))}
            for cid, text in CARE[rain]]

    return {
        "location": data["location"],
        "today": today.isoformat(),
        "week_start": wk,
        "week_end": (ws + timedelta(days=6)).isoformat(),
        "rain": rain,
        "rain_label": data["rainfall_labels"][str(rain)],
        "sun": sun,
        "size_sqm": garden.get("size_sqm"),
        "harvest": harvest,
        "sow": sow,
        "care": care,
        "hold": hold,
        "garden": rows,
        "crop_options": [{"id": c["id"], "title": c["name_en"], "local": c["name_si"]} for c in data["crops"]],
    }


# ---------- changing the garden ----------

def set_check(garden, data, today, item_id, done):
    kind, _, rest = item_id.partition(":")
    wk = week_start(today).isoformat()
    planted = garden.setdefault("planted", [])
    if kind == "sow":
        if rest not in {c["id"] for c in data["crops"]}:
            raise ValueError("unknown crop")
        if done:
            if not any(p["crop"] == rest and p["date"] >= wk for p in planted):
                planted.append({"crop": rest, "date": today.isoformat()})
        else:
            for p in reversed(planted):
                if p["crop"] == rest and p["date"] >= wk:
                    planted.remove(p)
                    break
    elif kind == "harvest":
        crop, _, d = rest.partition("@")
        hit = next((p for p in planted if p["crop"] == crop and p["date"] == d), None)
        if not hit:
            raise ValueError("unknown planting")
        if done:
            hit["harvested"] = today.isoformat()
        else:
            hit.pop("harvested", None)
    elif kind == "care":
        if rest not in {cid for lvl in CARE.values() for cid, _ in lvl}:
            raise ValueError("unknown care item")
        checks = garden.setdefault("checks", {})
        key = f"{wk}:{rest}"
        if done:
            checks[key] = True
        else:
            checks.pop(key, None)
        for k in [k for k in checks if not k.startswith(wk + ":")]:
            del checks[k]  # forget older weeks
    else:
        raise ValueError("unknown item")


def add_planted(garden, data, crop, day):
    if crop not in {c["id"] for c in data["crops"]}:
        raise ValueError("unknown crop")
    date.fromisoformat(day)
    planted = garden.setdefault("planted", [])
    if not any(p["crop"] == crop and p["date"] == day for p in planted):
        planted.append({"crop": crop, "date": day})


def remove_planted(garden, crop, day):
    garden["planted"] = [p for p in garden.get("planted", []) if not (p["crop"] == crop and p["date"] == day)]


def set_settings(garden, sun, size):
    if sun not in ("full", "partial"):
        raise ValueError("sun must be full or partial")
    size = float(size)
    if not 0 < size < 100000:
        raise ValueError("size must be a positive number")
    garden["sun"] = sun
    garden["size_sqm"] = int(size) if size == int(size) else size


# ---------- local model ----------

def note_facts(plan):
    return {
        "location": plan["location"],
        "rain_this_month": plan["rain_label"],
        "harvest_now": [h["title"] for h in plan["harvest"] if not h["done"]],
        "good_to_sow": [s["title"] for s in plan["sow"]][:6],
        "hold_off_until_drier": plan["hold"],
        "care_jobs": [c["title"] for c in plan["care"]],
    }


def clean_note(text):
    text = re.sub(r"[*_#`>]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    lead = re.compile(r"^(okay|ok|sure|alright|certainly|here(?:'|’)?s?[^.:!]{0,60})[,.:!]\s*", re.I)
    while lead.match(text):  # strip stacked intros like "Okay, here's your note:"
        text = lead.sub("", text, count=1)
    return text[:1].upper() + text[1:]


def ask_note(plan, model, host, lang):
    language = "Sinhala (write crop names in Sinhala and English)" if lang == "si" else "simple, friendly English"
    system = (
        "You are a warm, practical home-garden helper in Matara, Sri Lanka. "
        "Write a note of 2 to 3 sentences for the gardener about this week, using ONLY the facts in the JSON. "
        "Do not invent crops, dates, quantities or advice that the facts do not contain. "
        "Plain text only: no lists, no markdown, no greeting, no introduction. "
        f"Write in {language}."
    )
    body = json.dumps({
        "model": model,
        "stream": False,
        "options": {"temperature": 0.4, "num_predict": 220},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(note_facts(plan), ensure_ascii=False)},
        ],
    }).encode()
    req = urllib.request.Request(f"{host}/api/chat", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return clean_note(json.load(r)["message"]["content"])
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RuntimeError(f"Model '{model}' is not installed. Run: ollama pull {model}") from e
        raise RuntimeError(f"Ollama returned an error ({e.code})") from e
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError("Ollama is not running. Start it to get a weekly note.") from e
    except (KeyError, json.JSONDecodeError) as e:
        raise RuntimeError("Unexpected reply from Ollama") from e


# ---------- text version ----------

def plain_checklist(plan, note=None):
    lines = [f"Garden plan, {plan['location']}, {plan['week_start']} to {plan['week_end']}",
             f"Rain this month: {plan['rain_label']}", ""]
    if note:
        lines += [note, ""]

    def block(title, items, fmt):
        if items:
            lines.append(title)
            lines.extend(f"  [{'x' if i['done'] else ' '}] {fmt(i)}" for i in items)
            lines.append("")

    block("Harvest", plan["harvest"], lambda i: f"{i['title']}: {i['detail']}")
    block("Sow and plant", plan["sow"], lambda i: f"{i['title']} / {i['local']}: {i['detail']}. {i['tip']}")
    block("Care", plan["care"], lambda i: i["title"])
    if plan["hold"]:
        lines.append("Hold off until drier weather: " + ", ".join(plan["hold"]))
    return "\n".join(lines).rstrip()


def main():
    ap = argparse.ArgumentParser(description="Weekly garden checklist for Matara (text version).")
    ap.add_argument("--date", default=date.today().isoformat(), help="YYYY-MM-DD (default: today)")
    ap.add_argument("--garden", default=str(HERE / "garden.json"))
    ap.add_argument("--crops", default=str(HERE / "crops.json"))
    ap.add_argument("--model", default="gemma3")
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--lang", choices=["en", "si"], default="en")
    ap.add_argument("--no-ai", action="store_true", help="skip the local model")
    a = ap.parse_args()

    plan = build_plan(date.fromisoformat(a.date), load_json(a.garden), load_json(a.crops))
    note = None
    if not a.no_ai:
        try:
            note = ask_note(plan, a.model, a.host, a.lang)
        except RuntimeError as e:
            print(f"({e})\n")
    print(plain_checklist(plan, note))


if __name__ == "__main__":
    main()
