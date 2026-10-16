/* Finding a break by typing.
 *
 * Pure matching, no DOM, so it can be tested under Node (tests/test_search_js.py). site.js wires
 * it to the search box. Forgiving on purpose: "swamis", "Swami's" and "swami" all find Swami's,
 * "pb" finds Pacific Beach, "la jolla" finds the La Jolla breaks.
 *
 * An item is {name, area, aliases: [..]}.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.SwellSearch = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /* lower-case, no accents, no apostrophes, anything else becomes a single space */
  function normalize(s) {
    var t = String(s == null ? '' : s).toLowerCase();
    if (t.normalize) t = t.normalize('NFD').replace(/[̀-ͯ]/g, '');
    return t.replace(/['’`.]/g, '').replace(/[^a-z0-9]+/g, ' ').trim();
  }

  function words(s) { return s ? s.split(' ') : []; }

  function anyWordStartsWith(text, t) {
    return words(text).some(function (w) { return w.indexOf(t) === 0; });
  }

  /* How well one query word matches an item, 0 for not at all. */
  function tokenScore(f, t) {
    if (f.name.indexOf(t) === 0) return 100;
    for (var i = 0; i < f.aliases.length; i++) if (f.aliases[i] === t) return 90;
    if (anyWordStartsWith(f.name, t)) return 80;
    for (var j = 0; j < f.aliases.length; j++) if (anyWordStartsWith(f.aliases[j], t)) return 70;
    if (anyWordStartsWith(f.area, t)) return 40;
    if (t.length >= 3 && f.name.indexOf(t) !== -1) return 30;
    return 0;
  }

  function fields(item) {
    var aliases = [];
    (item.aliases || []).forEach(function (a) {
      var n = normalize(a);
      if (n) aliases.push(n);
    });
    return { name: normalize(item.name), area: normalize(item.area), aliases: aliases };
  }

  /* 0 when any word of the query finds nothing; otherwise higher is a better match. */
  function score(item, query) {
    var q = normalize(query);
    if (!q) return 0;
    var f = fields(item);
    var total = 0;
    var toks = words(q);
    for (var i = 0; i < toks.length; i++) {
      var s = tokenScore(f, toks[i]);
      if (!s) return 0;
      total += s;
    }
    if (f.name === q) total += 60;
    else if (f.name.indexOf(q) === 0) total += 30;
    return total;
  }

  /* Matching items, best first (ties alphabetical), at most `limit`. */
  function search(items, query, limit) {
    var scored = [];
    items.forEach(function (item) {
      var s = score(item, query);
      if (s > 0) scored.push({ item: item, s: s });
    });
    scored.sort(function (a, b) {
      if (a.s !== b.s) return b.s - a.s;
      return a.item.name < b.item.name ? -1 : a.item.name > b.item.name ? 1 : 0;
    });
    var out = scored.map(function (x) { return x.item; });
    return limit ? out.slice(0, limit) : out;
  }

  /* True if the item should stay visible while this is typed (everything does, for nothing typed). */
  function matches(item, query) {
    return !normalize(query) || score(item, query) > 0;
  }

  return { normalize: normalize, score: score, search: search, matches: matches };
}));
