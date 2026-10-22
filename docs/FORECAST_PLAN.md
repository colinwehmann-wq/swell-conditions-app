# Forecast accuracy plan

How to make the swell and wave predictions measurably better. The rule that drives the
order: **measure first, then change things, and only keep a change if the numbers improve.**

## What we have today

- One wave forecast from Open-Meteo. Probing the API shows its default ("best match") is
  identical to the Météo-France `meteofrance_wave` model at this location (~0.08° grid).
- One buoy-based correction (`h_scale`, `p_shift`) that nudges the model toward the live
  reading. It's clamped and has never been checked against outcomes.
- Only the primary swell is scored. Wind comes from the same global model.
- No record of how wrong any forecast has been.

## Findings from probing the data (Oct 2026)

| Model (Open-Meteo id) | Total Hs / period | Primary swell | Secondary swell |
|---|---|---|---|
| default / `meteofrance_wave` | yes | yes | yes |
| `ncep_gfswave016` (NOAA GFS-Wave, finer grid) | yes | yes | yes |
| `ncep_gfswave025` | yes | yes | yes |
| `gwam` (DWD) | yes | yes | no |
| `ecmwf_wam`, `ecmwf_wam025` | yes | **no** | **no** |

So ECMWF can only inform *total* height and period in a blend, not the swell fields. The
models also disagree noticeably (same hour, same cell: 1.04 m vs 0.66 m primary swell, against
a buoy reading of about 1.0 m), which is exactly why we need to measure them.

NDBC keeps ~45 days of 30-minute observations per buoy, so the "what actually happened" side
can be backfilled immediately. The forecast side cannot, so it starts accumulating now.

## Phase 1: measure accuracy

1. **Log every forecast.** `sources/verify.py` saves each model's forecast at the two buoy
   locations for the next 72 hours (every 3 hours): issue time, valid time, lead hours, total
   Hs and period, both swell trains, wind-wave height. Four models plus the default.
2. **Log what really happened.** The same run saves the live buoy readings (46224, 46225).
3. **Keep the log off the Actions cache** (it can be evicted). It lives on an orphan
   `forecast-log` branch, one JSONL file per month, appended by the scheduled workflow.
   No personal data, so a public branch is fine. The `check` job needs `contents: write`.
4. **Score it.** `tools/skill_report.py` pairs each forecast with the buoy reading at its valid
   time and reports bias, mean absolute error and RMSE by model and lead bucket (0–6, 6–12,
   12–24, 24–48, 48–72 h), with circular error for direction.
5. **Tests** for the pairing, circular error, lead bucketing, dedupe and the log store.

Note: these buoys have no anemometer, so wind can't be verified yet. That needs a wind
observation source (Phase 4).

**Done when** the log fills on every run and `skill_report.py` prints an error table. Trust it
after 2–4 weeks of data.

### Phase 1 status

Built and tested (Oct 14, 2026). The first live run logged 10 forecasts (5 models × 2 buoys) and
backfilled 4,332 buoy readings (45 days). A rerun logged nothing new, as intended.

Known gaps, deliberately left for later:

- **Total period isn't scored.** The models' `wave_period` is nearer a peak period (~13 s) and
  NDBC's `.spec` average period is ~8 s, so comparing them would be misleading. Fair comparison
  needs the buoy's dominant period (DPD, in the `.txt` feed). The forecast side is already logged.
- **Wind isn't verified** (no anemometer on these buoys).
- **Models are checked at the buoy, not at each break.** That isolates model quality from
  coastline effects; per-break behaviour is a Phase 4 question.

First signal, from only two paired readings (anecdotal, not a result): the default model's swell
period ran about 3 s short of the buoy while `ncep_gfswave016` was within 0.3 s. Wait for the
table to fill before acting on it.

## Phase 2: blend several wave models

1. Fetch more than one model; keep each as its own series.
2. Blend per variable. Totals can use all models; swell fields only the models that have them.
3. Start with equal weights, then weight by Phase 1 error per lead bucket. Weight changes go in
   through a reviewed config edit, never automatically.
4. Calibrate each model to the buoy before blending.
5. Replace the confidence label (today just days of lead) with lead time plus model spread.
6. Fall back cleanly when a model is missing or returns nulls.
7. Run old and new side by side in the log; switch only after at least two weeks of lower error.

**Done when** the blend beats the single model in `skill_report.py`.

## Phase 3: score both swell trains (built Oct 14, 2026)

The plan was to "combine the trains". Backtesting before building showed that how you combine
them matters, and the obvious way (add the energies in full) makes the production model's
height *worse*. So the rules below were chosen from 45 days of hindcast against both buoys, then
re-checked through the real calibration code (old vs new, 16 comparisons: 2 models × 2 buoys × 4
lead times; the new way won every one).

| Quantity | Rule | Why | Effect (default model, vs buoy) |
|---|---|---|---|
| Height | primary + **half** the secondary's energy, counting only the part that reaches the break | the buoy's "swell" holds both trains, so primary alone runs low; the full secondary overshoots | 0.107 → 0.101 m at +6 h |
| Period | power-weighted mean across the trains | the model's period runs ~3 s short of the buoy's peak period; this closes part of it | 1.93 → 1.66 s at +6 h (GFS: 2.19 → 1.71) |
| Direction | longest-period train with ≥25% of the energy | matches what the buoy's swell direction reports | 13.6° → 10.4° (GFS: 18.3° → 12.2°) |

How it's wired: `evaluate.combine_swell` / `model_trains`; calibration compares the buoy with
*all* the model's swell (the buoy sees everything), while scoring at a break counts only what
reaches it (full inside the swell window, fading to nothing 45° outside). A secondary under 8 s is
chop and ignored. Single-train data behaves exactly as before. The spot page mentions a real
secondary ("plus W 1.5 ft at 9 s", or "off-angle"), and `data/latest.json` carries it.

The accuracy report now has "both trains" rows beside the primary-only ones, computed from the
log with the same code, so the live data keeps checking this choice.

**Honest limits:** the backtest used the model's own recent analyses (hindcast), not true
archived forecasts, at two buoys. The 0.5 energy weight was fitted on that one dataset. Revisit
once the live log has weeks of real forecasts.

### Finding: near-term, "nothing changes" beats the model

The same backtests show that for the next ~6–12 hours, simply assuming the buoy reading stays
put beats the calibrated model trend (height error 0.089 m vs 0.101–0.115 m at +6 h; period
1.29 s vs 1.66–1.93 s). The model only wins from roughly +24 h (height) to +48 h (period). That's
the shape of a lead-time-aware blend: lean on the live buoy early, hand over to the model later.
It's the most promising accuracy gain found so far, and the live log (which already scores
persistence) is the right place to confirm it before building it. Treat it as the first thing to
check when the skill table has data.

## Phase 4: pick the next upgrade from the data

Let the error table decide:

- Error grows with lead time: add upstream buoys (Catalina Ridge 46025, Tanner Banks 46047).
- Direction error dominates: use NDBC/CDIP directional spectra instead of 22.5° compass text.
- "Clean" calls keep missing: NWS gridded wind plus live nearby wind observations.
- One break is always off in size: a per-spot size factor, or CDIP's MOP nearshore model. Its live
  forecast feed is confirmed (3-hourly, ~10 days, one point per ~100 m, over OPeNDAP) and is now
  logged beside the app's model for every break (`sources/cdip.py`, `tools/mop_report.py`).
- Small extras: observed vs predicted water level, the NWS surf zone forecast as a sanity check.
- Later: a real "was it good?" loop with session ratings or surf cams.

## Notes

- All of Phases 1–3 use the same free sources and need no new accounts.
- Open-Meteo's free API is for non-commercial use. Before charging for the service, read their
  terms and plan for a paid plan or another provider. NOAA data is free to use.
