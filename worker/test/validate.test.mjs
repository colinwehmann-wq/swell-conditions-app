import test from "node:test";
import assert from "node:assert/strict";
import { clean, DEFAULT_PREFS, DEFAULT_ALERTS, MAX_BREAKS } from "../src/validate.js";

const ok = (input) => {
  const r = clean(input);
  assert.equal(r.ok, true, JSON.stringify(r.errors));
  return r.profile;
};
const bad = (input) => {
  const r = clean(input);
  assert.equal(r.ok, false);
  return r.errors.join(" | ");
};

test("a bare list of breaks gets the defaults", () => {
  const p = ok({ breaks: ["swamis"] });
  assert.deepEqual(p.prefs, DEFAULT_PREFS);
  assert.deepEqual(p.alerts, DEFAULT_ALERTS);
  assert.deepEqual(p.overrides, {});
  assert.equal(p.v, 1);
});

test("a full profile round-trips", () => {
  const input = {
    name: "Colin",
    breaks: ["swamis", "windansea"],
    prefs: { height_ft: [3, 6], period_min_s: 10, wind: "offshore", wind_max_kn: 15, swell_dir_deg: [200, 300], tide_ft: [1, 4] },
    overrides: { windansea: { height_ft: [4, 8] } },
    alerts: { lead_min: 90, min_hours: 2, quiet_from: 22, quiet_to: 4 },
  };
  assert.deepEqual(ok(input), { v: 1, ...input });
});

test("unknown keys are dropped", () => {
  const p = ok({ breaks: ["swamis"], admin: true, prefs: { height_ft: [2, 5], evil: 1 } });
  assert.equal(p.admin, undefined);
  assert.equal(p.prefs.evil, undefined);
});

test("breaks: names, duplicates and the cap", () => {
  assert.deepEqual(ok({ breaks: ["swamis", "swamis", "d-street"] }).breaks, ["swamis", "d-street"]);
  assert.match(bad({ breaks: ["Swamis"] }), /not a valid break name/);
  assert.match(bad({ breaks: ["../etc"] }), /not a valid break name/);
  assert.match(bad({ breaks: "swamis" }), /list of break names/);
  assert.match(bad({}), /list of break names/);
  assert.match(bad({ breaks: Array.from({ length: MAX_BREAKS + 1 }, (_, i) => `b${i}`) }), /at most/);
});

test("height must be an ordered pair inside 0 to 30 ft", () => {
  assert.match(bad({ breaks: [], prefs: { height_ft: [6, 3] } }), /low to high/);
  assert.match(bad({ breaks: [], prefs: { height_ft: [3] } }), /two numbers/);
  assert.match(bad({ breaks: [], prefs: { height_ft: [3, 99] } }), /between 0 and 30/);
  assert.match(bad({ breaks: [], prefs: { height_ft: ["3", "6"] } }), /two numbers/);
});

test("a swell window may wrap past north", () => {
  assert.deepEqual(ok({ breaks: [], prefs: { swell_dir_deg: [340, 20] } }).prefs.swell_dir_deg, [340, 20]);
  assert.match(bad({ breaks: [], prefs: { swell_dir_deg: [0, 400] } }), /between 0 and 360/);
});

test("null means any direction and any tide", () => {
  const p = ok({ breaks: [], prefs: { swell_dir_deg: null, tide_ft: null } });
  assert.equal(p.prefs.swell_dir_deg, null);
  assert.equal(p.prefs.tide_ft, null);
});

test("wind mode, speed and period", () => {
  assert.match(bad({ breaks: [], prefs: { wind: "gusty" } }), /one of/);
  assert.match(bad({ breaks: [], prefs: { wind_max_kn: -1 } }), /0 to 40/);
  assert.match(bad({ breaks: [], prefs: { period_min_s: 99 } }), /0 to 25/);
  assert.equal(ok({ breaks: [], prefs: { wind: "any" } }).prefs.wind, "any");
});

test("overrides only for breaks in the profile, and they stay partial", () => {
  const p = ok({ breaks: ["swamis"], overrides: { swamis: { wind: "offshore" } } });
  assert.deepEqual(p.overrides.swamis, { wind: "offshore" });
  assert.match(bad({ breaks: ["swamis"], overrides: { windansea: { wind: "any" } } }), /not in this profile/);
  assert.match(bad({ breaks: ["swamis"], overrides: { swamis: { height_ft: [9, 1] } } }), /overrides\.swamis\.height_ft/);
});

test("alerts: lead time, minimum hours and quiet hours", () => {
  assert.match(bad({ breaks: [], alerts: { lead_min: 5 } }), /30 to 240/);
  assert.match(bad({ breaks: [], alerts: { min_hours: 0 } }), /1 to 8/);
  assert.match(bad({ breaks: [], alerts: { quiet_from: 22 } }), /go together/);
  assert.match(bad({ breaks: [], alerts: { quiet_from: 25, quiet_to: 4 } }), /0 to 23/);
  assert.deepEqual(ok({ breaks: [], alerts: { quiet_from: 0, quiet_to: 5 } }).alerts.quiet_from, 0);
});

test("name is trimmed and stripped of markup characters", () => {
  assert.equal(ok({ breaks: [], name: "  <b>Colin</b> " }).name, "bColin/b");
  assert.match(bad({ breaks: [], name: "x".repeat(41) }), /40 characters/);
});

test("not an object", () => {
  assert.match(bad(null), /JSON object/);
  assert.match(bad([]), /JSON object/);
  assert.match(bad("hi"), /JSON object/);
});
