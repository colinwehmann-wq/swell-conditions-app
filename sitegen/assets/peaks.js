/* Which peak should the top of the page name right now?
 *
 * The site is rebuilt a few times a day, so the headline it was built with goes stale the
 * moment the peak it names passes. The page therefore carries every upcoming peak and this
 * picks the next one from the visitor's clock. It mirrors `pick_next_peak` / `peak_title` in
 * sitegen/build.py: tests/test_peaks_js.py runs both against the same scenarios, so keep the
 * two in step.
 *
 * A peak is {slug, name, date "YYYY-MM-DD" (Pacific), time (ISO), time_label, weekday, score
 * (0-100), rating, band, label, sub}.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.SwellPeaks = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var STRONG = 70;      // same bar as a GO (a 7)
  var RIDEABLE = 50;

  function ahead(peaks, nowMs) {
    return peaks.filter(function (p) { return Date.parse(p.time) > nowMs; });
  }

  /* Earliest day that still has a strong peak ahead (best spot that day); failing that, the
     best rideable peak. Ties go to the earlier time. Null when nothing is worth it. */
  function pick(peaks, nowMs) {
    var future = ahead(peaks, nowMs);
    var strong = future.filter(function (p) { return p.score >= STRONG; });
    if (strong.length) {
      return strong.slice().sort(function (a, b) {
        if (a.date !== b.date) return a.date < b.date ? -1 : 1;
        if (a.score !== b.score) return b.score - a.score;
        return Date.parse(a.time) - Date.parse(b.time);
      })[0];
    }
    var ok = future.filter(function (p) { return p.score >= RIDEABLE; });
    if (!ok.length) return null;
    return ok.slice().sort(function (a, b) {
      if (a.score !== b.score) return b.score - a.score;
      return Date.parse(a.time) - Date.parse(b.time);
    })[0];
  }

  /* Whole days from one "YYYY-MM-DD" to another. */
  function dayDiff(fromYmd, toYmd) {
    function utc(s) { var a = s.split('-'); return Date.UTC(+a[0], +a[1] - 1, +a[2]); }
    return Math.round((utc(toYmd) - utc(fromYmd)) / 86400000);
  }

  function title(p, lead) {
    if (lead === 0) return 'Today, ' + p.name + ' peaks around ' + p.time_label + '.';
    if (lead === 1) return 'Tomorrow is the one — ' + p.name + ' peaks around ' + p.time_label + '.';
    return 'Not today. Best bet: ' + p.weekday + ' at ' + p.name + '.';
  }

  /* The look-ahead headline for this moment. `todayYmd` is today's date in Pacific time. */
  function headline(peaks, nowMs, todayYmd) {
    var p = pick(peaks, nowMs);
    if (!p) {
      return {
        kicker: 'Looking ahead',
        title: 'A flat spell.',
        sub: "Nothing worth paddling out for this week. We'll tell you when that changes.",
        fig: null,
        anchor: null
      };
    }
    return {
      kicker: 'Looking ahead',
      title: title(p, dayDiff(todayYmd, p.date)),
      sub: p.sub,
      fig: { slug: p.slug, name: p.name, rating: p.rating, band: p.band, label: p.label },
      anchor: Date.parse(p.time)
    };
  }

  return { STRONG: STRONG, RIDEABLE: RIDEABLE, pick: pick, title: title, dayDiff: dayDiff, headline: headline };
}));
