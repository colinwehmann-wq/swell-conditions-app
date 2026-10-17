// What a profile is, and the only shapes the service will store.
//
// A profile is somebody's saved breaks plus the conditions they call ideal:
//
//   { v: 1, name: "Colin",
//     breaks: ["swamis", "windansea"],
//     prefs:  { height_ft: [3, 6], period_min_s: 10, wind: "offshore", wind_max_kn: 12,
//               swell_dir_deg: [200, 300], tide_ft: [1, 4] },
//     overrides: { windansea: { height_ft: [4, 8] } },     // per-break changes, same keys as prefs
//     alerts: { lead_min: 60, min_hours: 1, quiet_from: 22, quiet_to: 4 } }
//
// Heights are feet, periods seconds, directions compass degrees the swell/wind comes FROM (a
// direction window may wrap past 360), tide feet above MLLW. `wind` is "offshore" (only offshore
// wind counts), "light" (any direction, but under wind_max_kn) or "any".
//
// `clean` returns { ok: true, profile } with unknown keys dropped and everything coerced to the
// canonical shape, or { ok: false, errors: [...] }. Nothing the service stores skips it.

export const VERSION = 1;
export const MAX_BREAKS = 40;
export const WIND_MODES = ["offshore", "light", "any"];

export const DEFAULT_PREFS = {
  height_ft: [3, 8],
  period_min_s: 8,
  wind: "light",
  wind_max_kn: 12,
  swell_dir_deg: null,
  tide_ft: null,
};

export const DEFAULT_ALERTS = { lead_min: 60, min_hours: 1, quiet_from: null, quiet_to: null };

const SLUG = /^[a-z0-9][a-z0-9-]{0,39}$/;

const isNum = (x) => typeof x === "number" && Number.isFinite(x);
const round1 = (x) => Math.round(x * 10) / 10;

function range(value, lo, hi, label, errors, { ordered = true } = {}) {
  if (!Array.isArray(value) || value.length !== 2 || !value.every(isNum)) {
    errors.push(`${label} must be two numbers, like [3, 6]`);
    return null;
  }
  const [a, b] = value;
  if (a < lo || b > hi || a > hi || b < lo) {
    errors.push(`${label} must be between ${lo} and ${hi}`);
    return null;
  }
  if (ordered && a > b) {
    errors.push(`${label} must go from low to high`);
    return null;
  }
  return [round1(a), round1(b)];
}

// Preferences, or a partial set of them (`partial`: per-break overrides, where leaving a key out
// means "same as the profile's").
export function cleanPrefs(input, label, errors, partial = false) {
  const out = {};
  if (input === undefined || input === null) return partial ? out : { ...DEFAULT_PREFS };
  if (typeof input !== "object" || Array.isArray(input)) {
    errors.push(`${label} must be an object`);
    return out;
  }
  // swell_dir_deg and tide_ft may be an explicit null ("any direction", "any tide").
  const given = (k) => input[k] !== undefined && (input[k] !== null || k === "swell_dir_deg" || k === "tide_ft");
  const pick = (k, build) => {
    if (given(k)) out[k] = build(input[k]);
    else if (!partial) out[k] = DEFAULT_PREFS[k];
  };

  pick("height_ft", (v) => range(v, 0, 30, `${label}.height_ft`, errors) ?? DEFAULT_PREFS.height_ft);
  pick("period_min_s", (v) => {
    if (!isNum(v) || v < 0 || v > 25) {
      errors.push(`${label}.period_min_s must be a number from 0 to 25`);
      return DEFAULT_PREFS.period_min_s;
    }
    return round1(v);
  });
  pick("wind", (v) => {
    if (!WIND_MODES.includes(v)) {
      errors.push(`${label}.wind must be one of ${WIND_MODES.join(", ")}`);
      return DEFAULT_PREFS.wind;
    }
    return v;
  });
  pick("wind_max_kn", (v) => {
    if (!isNum(v) || v < 0 || v > 40) {
      errors.push(`${label}.wind_max_kn must be a number from 0 to 40`);
      return DEFAULT_PREFS.wind_max_kn;
    }
    return round1(v);
  });
  // Direction windows may wrap (340 to 20), so they are not forced into low-to-high order.
  pick("swell_dir_deg", (v) => (v === null ? null : range(v, 0, 360, `${label}.swell_dir_deg`, errors, { ordered: false })));
  pick("tide_ft", (v) => (v === null ? null : range(v, -3, 8, `${label}.tide_ft`, errors)));
  return out;
}

function cleanAlerts(input, errors) {
  const out = { ...DEFAULT_ALERTS };
  if (input === undefined || input === null) return out;
  if (typeof input !== "object" || Array.isArray(input)) {
    errors.push("alerts must be an object");
    return out;
  }
  if (input.lead_min !== undefined) {
    if (!isNum(input.lead_min) || input.lead_min < 30 || input.lead_min > 240) errors.push("alerts.lead_min must be 30 to 240 minutes");
    else out.lead_min = Math.round(input.lead_min);
  }
  if (input.min_hours !== undefined) {
    if (!isNum(input.min_hours) || input.min_hours < 1 || input.min_hours > 8) errors.push("alerts.min_hours must be 1 to 8");
    else out.min_hours = Math.round(input.min_hours);
  }
  for (const k of ["quiet_from", "quiet_to"]) {
    if (input[k] === undefined || input[k] === null) continue;
    if (!Number.isInteger(input[k]) || input[k] < 0 || input[k] > 23) errors.push(`alerts.${k} must be an hour from 0 to 23`);
    else out[k] = input[k];
  }
  if ((out.quiet_from === null) !== (out.quiet_to === null)) errors.push("alerts.quiet_from and quiet_to go together");
  return out;
}

export function clean(input) {
  const errors = [];
  if (typeof input !== "object" || input === null || Array.isArray(input)) {
    return { ok: false, errors: ["profile must be a JSON object"] };
  }

  let name = "";
  if (input.name !== undefined && input.name !== null) {
    if (typeof input.name !== "string" || input.name.length > 40) errors.push("name must be text of 40 characters or fewer");
    else name = input.name.replace(/[\u0000-\u001f<>]/g, "").trim();
  }

  const breaks = [];
  if (!Array.isArray(input.breaks)) errors.push("breaks must be a list of break names");
  else {
    if (input.breaks.length > MAX_BREAKS) errors.push(`breaks can hold at most ${MAX_BREAKS}`);
    for (const b of input.breaks.slice(0, MAX_BREAKS)) {
      if (typeof b !== "string" || !SLUG.test(b)) errors.push(`"${String(b).slice(0, 30)}" is not a valid break name`);
      else if (!breaks.includes(b)) breaks.push(b);
    }
  }

  const prefs = cleanPrefs(input.prefs, "prefs", errors);

  const overrides = {};
  if (input.overrides !== undefined && input.overrides !== null) {
    if (typeof input.overrides !== "object" || Array.isArray(input.overrides)) errors.push("overrides must be an object");
    else {
      for (const [slug, p] of Object.entries(input.overrides)) {
        if (!SLUG.test(slug)) errors.push(`"${slug.slice(0, 30)}" is not a valid break name`);
        else if (!breaks.includes(slug)) errors.push(`overrides.${slug}: that break is not in this profile`);
        else overrides[slug] = cleanPrefs(p, `overrides.${slug}`, errors, true);
      }
    }
  }

  const alerts = cleanAlerts(input.alerts, errors);

  if (errors.length) return { ok: false, errors };
  return { ok: true, profile: { v: VERSION, name, breaks, prefs, overrides, alerts } };
}
