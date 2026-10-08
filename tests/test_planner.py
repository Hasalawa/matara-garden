import copy
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import planner  # noqa: E402

DATA = planner.load_json(ROOT / "crops.json")
TODAY = date(2026, 10, 8)  # a Thursday; its week starts Monday 2026-10-05


def fresh_garden(**kw):
    g = {"size_sqm": 20, "sun": "full", "planted": []}
    g.update(kw)
    return g


class CropData(unittest.TestCase):
    def test_every_month_has_a_rain_level(self):
        for m in range(1, 13):
            self.assertIn(DATA["rainfall_level"][str(m)], (1, 2, 3, 4), f"month {m}")
        self.assertEqual(set(DATA["rainfall_labels"]), {"1", "2", "3", "4"})

    def test_crops_are_well_formed(self):
        ids = set()
        for c in DATA["crops"]:
            self.assertNotIn(c["id"], ids, "duplicate crop id")
            ids.add(c["id"])
            self.assertTrue(c["sow_months"] and all(1 <= m <= 12 for m in c["sow_months"]), c["id"])
            self.assertIn(c["rain_tolerance"], ("low", "medium", "high"), c["id"])
            self.assertIn(c["sun_need"], ("full", "partial_ok"), c["id"])
            self.assertGreater(c["days_to_harvest"], 0, c["id"])
            self.assertGreater(c["spacing_cm"], 0, c["id"])
            for k in ("name_en", "name_si", "method", "tip"):
                self.assertTrue(c[k].strip(), f"{c['id']} missing {k}")

    def test_every_rain_level_has_care_jobs(self):
        self.assertEqual(set(planner.CARE), {1, 2, 3, 4})


class Plan(unittest.TestCase):
    def test_plan_builds_for_every_month(self):
        for m in range(1, 13):
            p = planner.build_plan(date(2026, m, 15), fresh_garden(), DATA)
            self.assertTrue(p["care"], f"month {m}")
            self.assertEqual(p["week_start"] <= p["today"] <= p["week_end"], True)

    def test_week_runs_monday_to_sunday(self):
        p = planner.build_plan(TODAY, fresh_garden(), DATA)
        self.assertEqual((p["week_start"], p["week_end"]), ("2026-10-05", "2026-10-11"))

    def test_harvest_window_and_ready_text(self):
        g = fresh_garden(planted=[
            {"crop": "okra", "date": "2026-08-20"},       # ready 2026-10-14, 6 days away
            {"crop": "long_bean", "date": "2026-09-05"},  # ready 2026-11-09, too far
            {"crop": "kang_kung", "date": "2026-08-01"},  # long overdue
        ])
        p = planner.build_plan(TODAY, g, DATA)
        by = {h["title"]: h for h in p["harvest"]}
        self.assertIn("Okra", by)
        self.assertNotIn("Long bean", by)
        self.assertIn("Ready in 6 days", by["Okra"]["detail"])
        self.assertTrue(by["Water spinach (kang kung)"]["overdue"])

    def test_partial_shade_hides_full_sun_crops(self):
        p = planner.build_plan(date(2026, 3, 10), fresh_garden(sun="partial"), DATA)
        names = {s["title"] for s in p["sow"]}
        self.assertNotIn("Okra", names)
        self.assertIn("Gotukola", names)

    def test_rain_sensitive_crop_rules(self):
        data = copy.deepcopy(DATA)
        tomato = next(c for c in data["crops"] if c["id"] == "tomato")
        tomato["sow_months"] = [10, 12]
        very_wet = planner.build_plan(date(2026, 10, 8), fresh_garden(), data)   # level 4
        self.assertIn("Tomato", very_wet["hold"])
        self.assertNotIn("Tomato", {s["title"] for s in very_wet["sow"]})
        wet = planner.build_plan(date(2026, 12, 8), fresh_garden(), data)        # level 3
        t = next(s for s in wet["sow"] if s["title"] == "Tomato")
        self.assertTrue(t["caution"])

    def test_already_growing_flag(self):
        g = fresh_garden(planted=[{"crop": "long_bean", "date": "2026-09-05"}])
        p = planner.build_plan(TODAY, g, DATA)
        lb = next(s for s in p["sow"] if s["title"] == "Long bean")
        self.assertTrue(lb["growing"])
        self.assertFalse(lb["done"])


class Changes(unittest.TestCase):
    def test_sow_tick_adds_and_untick_removes(self):
        g = fresh_garden()
        planner.set_check(g, DATA, TODAY, "sow:brinjal", True)
        self.assertEqual(g["planted"], [{"crop": "brinjal", "date": "2026-10-08"}])
        planner.set_check(g, DATA, TODAY, "sow:brinjal", True)  # ticking twice doesn't duplicate
        self.assertEqual(len(g["planted"]), 1)
        self.assertTrue(next(s for s in planner.build_plan(TODAY, g, DATA)["sow"] if s["title"] == "Brinjal")["done"])
        planner.set_check(g, DATA, TODAY, "sow:brinjal", False)
        self.assertEqual(g["planted"], [])

    def test_untick_keeps_older_plantings(self):
        g = fresh_garden(planted=[{"crop": "brinjal", "date": "2026-09-01"}])
        planner.set_check(g, DATA, TODAY, "sow:brinjal", False)
        self.assertEqual(len(g["planted"]), 1)

    def test_harvest_tick_and_untick(self):
        g = fresh_garden(planted=[{"crop": "okra", "date": "2026-08-20"}])
        planner.set_check(g, DATA, TODAY, "harvest:okra@2026-08-20", True)
        self.assertEqual(g["planted"][0]["harvested"], "2026-10-08")
        item = planner.build_plan(TODAY, g, DATA)["harvest"][0]
        self.assertTrue(item["done"])
        planner.set_check(g, DATA, TODAY, "harvest:okra@2026-08-20", False)
        self.assertNotIn("harvested", g["planted"][0])

    def test_care_ticks_reset_each_week(self):
        g = fresh_garden()
        planner.set_check(g, DATA, TODAY, "care:drains", True)
        this_week = planner.build_plan(TODAY, g, DATA)["care"]
        self.assertTrue(next(c for c in this_week if c["id"] == "care:drains")["done"])
        next_week = planner.build_plan(date(2026, 10, 15), g, DATA)["care"]
        self.assertFalse(any(c["done"] for c in next_week))
        planner.set_check(g, DATA, date(2026, 10, 15), "care:drains", True)
        self.assertEqual(list(g["checks"]), ["2026-10-12:drains"])  # old week forgotten

    def test_bad_input_is_rejected(self):
        g = fresh_garden()
        for bad in ("sow:unicorn", "harvest:okra@2026-01-01", "care:nope", "wat:okra", "nocolon"):
            with self.assertRaises(ValueError, msg=bad):
                planner.set_check(g, DATA, TODAY, bad, True)
        with self.assertRaises(ValueError):
            planner.add_planted(g, DATA, "okra", "not-a-date")
        with self.assertRaises(ValueError):
            planner.set_settings(g, "moon", 20)
        with self.assertRaises(ValueError):
            planner.set_settings(g, "full", -5)

    def test_add_and_remove_planted(self):
        g = fresh_garden()
        planner.add_planted(g, DATA, "okra", "2026-09-01")
        planner.add_planted(g, DATA, "okra", "2026-09-01")
        self.assertEqual(len(g["planted"]), 1)
        planner.remove_planted(g, "okra", "2026-09-01")
        self.assertEqual(g["planted"], [])


class Note(unittest.TestCase):
    def test_clean_note_strips_markdown_and_intros(self):
        self.assertEqual(planner.clean_note("Okay, here's your note:\n**This week** is wet."), "This week is wet.")
        self.assertEqual(planner.clean_note("Sure! Here's a short note for you: Pick okra soon."), "Pick okra soon.")
        self.assertEqual(planner.clean_note("Pick okra before the rain."), "Pick okra before the rain.")
        self.assertEqual(planner.clean_note(""), "")

    def test_note_facts_only_contain_plan_data(self):
        p = planner.build_plan(TODAY, fresh_garden(), DATA)
        f = planner.note_facts(p)
        crop_names = {c["name_en"] for c in DATA["crops"]}
        self.assertTrue(set(f["good_to_sow"]) <= crop_names)

    def test_missing_ollama_gives_a_friendly_error(self):
        p = planner.build_plan(TODAY, fresh_garden(), DATA)
        with self.assertRaises(RuntimeError) as cm:
            planner.ask_note(p, "gemma3", "http://127.0.0.1:1", "en")
        self.assertIn("Ollama is not running", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
