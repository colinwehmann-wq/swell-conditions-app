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
})();
