/* Swell Check — progressive enhancement only. The site works without this file. */
(function () {
  'use strict';

  var root = document.documentElement;

  /* ---- theme: system -> light -> dark ---- */
  function choice() {
    try { return localStorage.getItem('theme') || 'system'; } catch (e) { return 'system'; }
  }
  function applyTheme(next) {
    if (next === 'light' || next === 'dark') root.setAttribute('data-theme', next);
    else root.removeAttribute('data-theme');
    try {
      if (next === 'system') localStorage.removeItem('theme');
      else localStorage.setItem('theme', next);
    } catch (e) { /* storage blocked: theme just won't persist */ }
  }
  var toggle = document.querySelector('[data-theme-toggle]');
  if (toggle) {
    var names = { system: 'match device', light: 'light', dark: 'dark' };
    var sync = function () {
      var label = 'Theme: ' + names[choice()];
      toggle.setAttribute('aria-label', label + '. Activate to change.');
      toggle.title = label;
    };
    sync();
    toggle.addEventListener('click', function () {
      applyTheme({ system: 'light', light: 'dark', dark: 'system' }[choice()]);
      sync();
    });
  }

  /* ---- tooltips (text only; data is untrusted, so never innerHTML) ---- */
  var tip = document.getElementById('tip');
  function show(el) {
    var raw = el.getAttribute('data-tip');
    if (!raw || !tip) return;
    tip.textContent = '';
    raw.split('|').filter(Boolean).forEach(function (line, i) {
      var node = document.createElement(i === 0 ? 'strong' : 'span');
      node.textContent = line;
      tip.appendChild(node);
    });
    tip.hidden = false;
    var r = el.getBoundingClientRect();
    var w = tip.offsetWidth, h = tip.offsetHeight;
    var left = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), window.innerWidth - w - 8);
    var top = r.top - h - 10;
    if (top < 8) top = r.bottom + 10;
    tip.style.left = left + 'px';
    tip.style.top = top + 'px';
  }
  function hide() { if (tip) tip.hidden = true; }
  function target(e) { return e.target && e.target.closest ? e.target.closest('[data-tip]') : null; }

  document.addEventListener('pointerover', function (e) { var el = target(e); if (el) show(el); });
  document.addEventListener('pointerout', function (e) { if (target(e)) hide(); });
  document.addEventListener('focusin', function (e) { var el = target(e); if (el) show(el); });
  document.addEventListener('focusout', function (e) { if (target(e)) hide(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') hide(); });
  window.addEventListener('scroll', hide, { passive: true });

  /* ---- copy topic ---- */
  document.querySelectorAll('[data-copy]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var text = btn.getAttribute('data-copy');
      var original = btn.textContent;
      function done() {
        btn.textContent = 'Copied';
        btn.setAttribute('data-done', '1');
        setTimeout(function () { btn.textContent = original; btn.removeAttribute('data-done'); }, 1600);
      }
      function fallback() {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        try { if (document.execCommand('copy')) done(); } catch (e) { /* nothing more to try */ }
        document.body.removeChild(ta);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, fallback);
      } else {
        fallback();
      }
    });
  });

  /* ---- "Updated 12 min ago" ---- */
  document.querySelectorAll('time[data-age]').forEach(function (el) {
    var t = new Date(el.getAttribute('datetime'));
    if (isNaN(t.getTime())) return;
    var mins = Math.floor((Date.now() - t.getTime()) / 60000);
    var text = null;
    if (mins < 1) text = 'just now';
    else if (mins < 60) text = mins + ' min ago';
    else if (mins < 24 * 60) text = Math.floor(mins / 60) + ' h ago';
    if (text) {
      el.title = el.textContent;
      el.textContent = 'Updated ' + text;
    }
  });

  /* ---- top of the page: move on to the next peak once the one on show has passed ----
     The page is rebuilt a few times a day, so its headline would otherwise keep naming a time
     that has already gone. The page carries every upcoming peak (#peaks-data) and
     data-anchor says when the text it was built with stops being true; after that this
     re-picks from the visitor's clock using SwellPeaks (assets/peaks.js). Text only, never
     innerHTML. With no script, or if anything here fails, the built text simply stays. */
  var hero = document.querySelector('[data-hero="root"]');
  var feed = document.getElementById('peaks-data');
  if (hero && feed && window.SwellPeaks) {
    var peaks = [];
    try { peaks = JSON.parse(feed.textContent) || []; } catch (e) { peaks = []; }
    var part = function (name) { return hero.querySelector('[data-hero="' + name + '"]'); };
    var ICON = { green: '✓', yellow: '!', red: '✕' };
    var CLS = { green: 'chip-good', yellow: 'chip-ok', red: 'chip-poor' };
    var timer = null;

    var pacificDate = function (ms) {
      try {
        return new Intl.DateTimeFormat('en-CA', {
          timeZone: 'America/Los_Angeles', year: 'numeric', month: '2-digit', day: '2-digit'
        }).format(new Date(ms));
      } catch (e) { return null; }
    };

    var showHeadline = function (h) {
      part('kicker').textContent = h.kicker;
      part('title').textContent = h.title;
      part('sub').textContent = h.sub;
      var fig = part('fig');
      if (!h.fig) { fig.hidden = true; return; }
      fig.hidden = false;
      fig.setAttribute('href', 'spots/' + encodeURIComponent(h.fig.slug) + '/');
      part('num').textContent = h.fig.rating.toFixed(1);
      part('name').textContent = h.fig.name;
      var chip = fig.querySelector('.chip');
      chip.className = 'chip chip-pill ' + CLS[h.fig.band];
      chip.querySelector('.chip-ico').textContent = ICON[h.fig.band];
      chip.querySelector('.chip-num').textContent = h.fig.rating.toFixed(1);
      chip.querySelector('.chip-lbl').textContent = h.fig.label;
    };

    var anchorMs = function () { return Date.parse(hero.getAttribute('data-anchor') || ''); };

    var schedule = function (atMs, nowMs) {
      if (timer) clearTimeout(timer);
      // a second past the moment, and never longer than a timer can hold
      var wait = Math.min(Math.max(atMs - nowMs + 1000, 1000), 2147483000);
      timer = setTimeout(function () { update(Date.now()); }, wait);
    };

    var update = function (nowMs) {
      var anchor = anchorMs();
      if (!isNaN(anchor) && nowMs < anchor) { schedule(anchor, nowMs); return; }   // still true
      var today = pacificDate(nowMs);
      if (!today) return;
      var h = window.SwellPeaks.headline(peaks, nowMs, today);
      showHeadline(h);
      hero.setAttribute('data-anchor', h.anchor ? new Date(h.anchor).toISOString() : '');
      if (h.anchor) schedule(h.anchor, nowMs);
    };

    // Timers are throttled in background tabs and stop while a laptop sleeps, so also look again
    // every minute and whenever the tab comes back.
    var recheck = function () {
      var anchor = anchorMs();
      if (isNaN(anchor) || Date.now() >= anchor) update(Date.now());
    };
    setInterval(recheck, 60000);
    document.addEventListener('visibilitychange', function () { if (!document.hidden) recheck(); });
    window.SwellHero = { update: update };    // lets a test set the clock
    update(Date.now());
  }
})();
