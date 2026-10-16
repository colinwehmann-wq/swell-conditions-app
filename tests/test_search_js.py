"""The break search (sitegen/assets/search.js), run under Node against the real roster, so these are
the things a visitor would actually type. Skipped when Node isn't installed (CI has it)."""
import json
import os
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEARCH_JS = os.path.join(ROOT, "sitegen", "assets", "search.js")
NODE = shutil.which("node")

RUNNER = """
const S = require(process.argv[1]);
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = input.queries.map(q => ({
  q: q,
  names: S.search(input.items, q, input.limit || 0).map(i => i.name),
  matches: input.items.map(i => S.matches(i, q)),
  normalized: S.normalize(q),
}));
process.stdout.write(JSON.stringify(out));
"""

ITEMS = [{"name": c["name"], "area": c["area"], "aliases": c.get("aliases", [])} for c in config.SPOTS]


def run(queries, limit=0, items=None):
    out = subprocess.run([NODE, "-e", RUNNER, SEARCH_JS],
                         input=json.dumps({"items": items or ITEMS, "queries": queries, "limit": limit}),
                         capture_output=True, text=True, timeout=60, check=True)
    return {r["q"]: r for r in json.loads(out.stdout)}


@unittest.skipUnless(NODE, "Node is not installed")
class Search(unittest.TestCase):
    def first(self, q):
        names = run([q])[q]["names"]
        return names[0] if names else None

    def test_punctuation_and_case_do_not_matter(self):
        for q in ("swamis", "Swami's", "SWAMI", "swami’s", "  swamis  "):
            self.assertEqual(self.first(q), "Swami's", q)

    def test_the_names_people_actually_use(self):
        cases = {
            "pb": "Pacific Beach", "ob": "Ocean Beach", "ib": "Imperial Beach", "mb": "Mission Beach",
            "windansea": "Windansea", "wind and sea": "Windansea", "blacks": "Blacks", "black's": "Blacks",
            "sunset": "Sunset Cliffs", "the cliffs": "Sunset Cliffs", "oside": "Oceanside Harbor",
            "d street": "D Street", "15th street": "Del Mar", "moonlight": "Moonlight Beach",
            "tourmaline": "Tourmaline", "scripps": "Scripps Pier", "shores": "La Jolla Shores",
            "sloughs": "Tijuana Sloughs", "border": "Tijuana Sloughs", "hotel del": "Coronado",
            "cardiff": "Cardiff Reef", "seaside": "Cardiff Reef", "fletchers": "Fletcher Cove",
            "tabletops": "Fletcher Cove", "beacons": "Beacon's", "grandview": "Grandview",
        }
        got = {q: self.first(q) for q in cases}
        self.assertEqual(got, cases)

    def test_an_area_finds_every_break_in_it(self):
        names = run(["la jolla"])["la jolla"]["names"]
        for expected in ("La Jolla Shores", "Windansea", "Scripps Pier", "Bird Rock"):
            self.assertIn(expected, names)
        self.assertEqual(names[0], "La Jolla Shores")      # the name match outranks an area match

    def test_every_break_is_found_by_its_own_name_and_by_each_alias(self):
        queries = []
        for c in config.SPOTS:
            queries.append(c["name"])
            queries.extend(c.get("aliases", []))
        results = run(queries)
        for c in config.SPOTS:
            for q in [c["name"]] + c.get("aliases", []):
                self.assertIn(c["name"], results[q]["names"], "%r should find %s" % (q, c["name"]))

    def test_an_exact_name_ranks_above_a_partial_one(self):
        self.assertEqual(self.first("ocean beach"), "Ocean Beach")
        self.assertEqual(self.first("pacific beach"), "Pacific Beach")

    def test_a_word_that_matches_nothing_finds_nothing(self):
        self.assertEqual(run(["zzzzz"])["zzzzz"]["names"], [])
        self.assertEqual(run(["swamis xyz"])["swamis xyz"]["names"], [])

    def test_nothing_typed_finds_nothing_to_show_but_filters_nothing_out(self):
        r = run(["", "   "])
        self.assertEqual(r[""]["names"], [])
        self.assertTrue(all(r[""]["matches"]))
        self.assertTrue(all(r["   "]["matches"]))

    def test_every_word_must_match(self):
        names = run(["la shores"])["la shores"]["names"]
        self.assertEqual(names, ["La Jolla Shores"])

    def test_the_limit_is_respected(self):
        self.assertEqual(len(run(["b"], limit=3)["b"]["names"]), 3)

    def test_matches_agrees_with_search_for_directory_filtering(self):
        r = run(["pier"])["pier"]
        shown = [i["name"] for i, m in zip(ITEMS, r["matches"]) if m]
        self.assertEqual(sorted(shown), sorted(r["names"]))
        for expected in ("Oceanside Pier", "Scripps Pier"):
            self.assertIn(expected, shown)

    def test_accents_are_ignored(self):
        items = [{"name": "Café Beach", "area": "X", "aliases": []}]
        self.assertEqual(run(["cafe"], items=items)["cafe"]["names"], ["Café Beach"])


if __name__ == "__main__":
    unittest.main()
