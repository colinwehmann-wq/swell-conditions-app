/* The profile page: pick your breaks and what you call ideal, and get an alert about an hour
 * before they line up. Talks to the profile service (worker/); the shape it accepts is
 * worker/src/validate.js.
 *
 * The top half is plain functions (form values <-> a profile) so tests/test_profile_js.py can run
 * them under Node. The bottom half wires the page and only runs in a browser. Text only ever goes
 * in with textContent, so nothing typed or stored can turn into markup.
 *
 * Your profile is identified by a long random id. It lives in this browser (localStorage) and in
 * the page address after the # (which is never sent to any server), so the private link
 * https://.../profile/#<id> opens the same profile on another device.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.SwellProfile = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
  var DIRECTIONS = COMPASS.map(function (name, i) { return { name: name, deg: i * 22.5 }; });

  var DEFAULTS = {
    breaks: [], height_min: '3', height_max: '8', period_min: '8', wind: 'light', wind_max: '12',
    dir_from: '', dir_to: '', tide_min: '', tide_max: '', lead_min: '60', min_hours: '1',
    quiet_on: false, quiet_from: '22', quiet_to: '4'
  };

  function num(text) {
    if (text === null || text === undefined) return null;
    var s = String(text).trim();
    if (s === '') return null;
    var n = Number(s);
    return isFinite(n) ? n : NaN;
  }

  /* Form values -> { profile } to send, or { errors: [...] } in plain words. The service checks
     everything again; this only gives a friendlier message first. */
  function buildProfile(v) {
    var errors = [];
    var breaks = (v.breaks || []).slice();
    if (!breaks.length) errors.push('Pick at least one break.');

    var hmin = num(v.height_min), hmax = num(v.height_max);
    if (hmin === null || hmax === null || isNaN(hmin) || isNaN(hmax)) errors.push('Give the smallest and biggest wave height you want, in feet.');
    else if (hmin > hmax) errors.push('The smallest wave height can\'t be bigger than the biggest.');
    else if (hmin < 0 || hmax > 30) errors.push('Wave height has to be between 0 and 30 feet.');

    var period = num(v.period_min);
    if (period === null || isNaN(period) || period < 0 || period > 25) errors.push('Minimum swell period has to be between 0 and 25 seconds.');

    var wind = v.wind || 'light';
    var windMax = num(v.wind_max);
    if (wind !== 'any' && (windMax === null || isNaN(windMax) || windMax < 0 || windMax > 40)) errors.push('Top wind speed has to be between 0 and 40 knots.');

    var dir = null;
    var from = num(v.dir_from), to = num(v.dir_to);
    if ((from === null) !== (to === null)) errors.push('Pick both ends of the swell direction, or leave both on "any".');
    else if (from !== null) dir = [from, to];

    var tide = null;
    var tmin = num(v.tide_min), tmax = num(v.tide_max);
    if ((tmin === null) !== (tmax === null)) errors.push('Give both a lowest and a highest tide, or leave both empty for any tide.');
    else if (tmin !== null) {
      if (isNaN(tmin) || isNaN(tmax) || tmin > tmax) errors.push('The lowest tide can\'t be higher than the highest.');
      else tide = [tmin, tmax];
    }

    var alerts = { lead_min: Number(v.lead_min) || 60, min_hours: Number(v.min_hours) || 1, quiet_from: null, quiet_to: null };
    if (v.quiet_on) {
      alerts.quiet_from = Number(v.quiet_from);
      alerts.quiet_to = Number(v.quiet_to);
      if (alerts.quiet_from === alerts.quiet_to) errors.push('Quiet hours need a start and an end that differ.');
    }

    if (errors.length) return { errors: errors };
    return {
      profile: {
        v: 1,
        breaks: breaks,
        prefs: {
          height_ft: [hmin, hmax],
          period_min_s: period,
          wind: wind,
          wind_max_kn: wind === 'any' || windMax === null ? 12 : windMax,
          swell_dir_deg: dir,
          tide_ft: tide
        },
        overrides: {},
        alerts: alerts
      }
    };
  }

  function nearestDirection(deg) {
    var best = DIRECTIONS[0], bestGap = 999;
    DIRECTIONS.forEach(function (d) {
      var gap = Math.abs(((deg - d.deg + 540) % 360) - 180);
      if (gap < bestGap) { best = d; bestGap = gap; }
    });
    return String(best.deg);
  }

  /* A stored profile -> form values. */
  function valuesFromProfile(p) {
    var v = JSON.parse(JSON.stringify(DEFAULTS));
    if (!p) return v;
    v.breaks = (p.breaks || []).slice();
    var pr = p.prefs || {};
    if (pr.height_ft) { v.height_min = String(pr.height_ft[0]); v.height_max = String(pr.height_ft[1]); }
    if (pr.period_min_s !== undefined) v.period_min = String(pr.period_min_s);
    if (pr.wind) v.wind = pr.wind;
    if (pr.wind_max_kn !== undefined) v.wind_max = String(pr.wind_max_kn);
    if (pr.swell_dir_deg) { v.dir_from = nearestDirection(pr.swell_dir_deg[0]); v.dir_to = nearestDirection(pr.swell_dir_deg[1]); }
    if (pr.tide_ft) { v.tide_min = String(pr.tide_ft[0]); v.tide_max = String(pr.tide_ft[1]); }
    var al = p.alerts || {};
    if (al.lead_min) v.lead_min = String(al.lead_min);
    if (al.min_hours) v.min_hours = String(al.min_hours);
    if (al.quiet_from !== null && al.quiet_from !== undefined && al.quiet_to !== null && al.quiet_to !== undefined) {
      v.quiet_on = true; v.quiet_from = String(al.quiet_from); v.quiet_to = String(al.quiet_to);
    }
    return v;
  }

  /* "swell-ab12..." -> the links a person needs to subscribe. */
  function subscribeLinks(topic, host) {
    host = host || 'ntfy.sh';
    return { app: 'ntfy://' + host + '/' + topic, web: 'https://' + host + '/' + topic };
  }

  var ID_RE = /^[A-Za-z0-9_-]{22}$/;
  function validId(id) { return typeof id === 'string' && ID_RE.test(id); }

  var api = {
    DIRECTIONS: DIRECTIONS, DEFAULTS: DEFAULTS, buildProfile: buildProfile, valuesFromProfile: valuesFromProfile,
    subscribeLinks: subscribeLinks, validId: validId, nearestDirection: nearestDirection
  };

  // ----------------------------------------------------------------------------- the page
  if (typeof document === 'undefined') return api;

  var rootEl = document.querySelector('[data-profile-root]');
  if (!rootEl) return api;

  var API = (rootEl.getAttribute('data-api') || '').replace(/\/+$/, '');
  var KEY = 'swell-profile-id';
  var form = rootEl.querySelector('form');
  var statusEl = rootEl.querySelector('[data-pf-status]');
  var errorsEl = rootEl.querySelector('[data-pf-errors]');
  var savedEl = rootEl.querySelector('[data-pf-saved]');
  var saveBtn = rootEl.querySelector('[data-pf-save]');
  var deleteBtn = rootEl.querySelector('[data-pf-delete]');
  var id = null;
  var topic = null;

  function store(value) {
    try { if (value) localStorage.setItem(KEY, value); else localStorage.removeItem(KEY); } catch (e) { /* private mode: the link still works */ }
  }
  function stored() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }
  function say(text) { statusEl.textContent = text || ''; }
  function showErrors(list) {
    errorsEl.textContent = '';
    errorsEl.hidden = !list.length;
    list.forEach(function (m) { var li = document.createElement('li'); li.textContent = m; errorsEl.appendChild(li); });
    if (list.length) errorsEl.scrollIntoView({ block: 'nearest' });
  }

  function readForm() {
    var f = form.elements;
    var checked = Array.prototype.slice.call(form.querySelectorAll('input[name="break"]:checked')).map(function (b) { return b.value; });
    var wind = form.querySelector('input[name="wind"]:checked');
    return {
      breaks: checked, height_min: f.height_min.value, height_max: f.height_max.value, period_min: f.period_min.value,
      wind: wind ? wind.value : 'light', wind_max: f.wind_max.value, dir_from: f.dir_from.value, dir_to: f.dir_to.value,
      tide_min: f.tide_min.value, tide_max: f.tide_max.value, lead_min: f.lead_min.value, min_hours: f.min_hours.value,
      quiet_on: f.quiet_on.checked, quiet_from: f.quiet_from.value, quiet_to: f.quiet_to.value
    };
  }

  function fillForm(v) {
    var f = form.elements;
    Array.prototype.forEach.call(form.querySelectorAll('input[name="break"]'), function (b) { b.checked = v.breaks.indexOf(b.value) !== -1; });
    ['height_min', 'height_max', 'period_min', 'wind_max', 'dir_from', 'dir_to', 'tide_min', 'tide_max', 'lead_min', 'min_hours', 'quiet_from', 'quiet_to']
      .forEach(function (k) { f[k].value = v[k]; });
    Array.prototype.forEach.call(form.querySelectorAll('input[name="wind"]'), function (r) { r.checked = r.value === v.wind; });
    f.quiet_on.checked = !!v.quiet_on;
    syncDependent();
  }

  function syncDependent() {
    var f = form.elements;
    var wind = form.querySelector('input[name="wind"]:checked');
    f.wind_max.disabled = !!wind && wind.value === 'any';
    f.quiet_from.disabled = f.quiet_to.disabled = !f.quiet_on.checked;
  }

  function call(method, path, body) {
    var opts = { method: method, headers: {} };
    if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers['Content-Type'] = 'application/json'; }
    return fetch(API + path, opts).then(function (res) {
      if (res.status === 204) return { status: 204, data: null };
      return res.json().then(function (data) { return { status: res.status, data: data }; }, function () { return { status: res.status, data: null }; });
    });
  }

  function privateLink() {
    return location.origin + location.pathname + '#' + id;
  }

  function showSaved() {
    var links = subscribeLinks(topic);
    savedEl.hidden = false;
    savedEl.querySelector('[data-pf-link]').value = privateLink();
    savedEl.querySelector('[data-pf-topic]').textContent = topic;
    savedEl.querySelector('[data-pf-app]').setAttribute('href', links.app);
    savedEl.querySelector('[data-pf-web]').setAttribute('href', links.web);
    deleteBtn.hidden = false;
  }

  function adopt(data) {
    id = data.id;
    topic = data.topic;
    store(id);
    if (location.hash.slice(1) !== id) history.replaceState(null, '', '#' + id);
    showSaved();
  }

  function load(existing) {
    say('Loading your profile…');
    call('GET', '/api/profile/' + existing).then(function (r) {
      if (r.status === 200) {
        fillForm(valuesFromProfile(r.data.profile));
        adopt(r.data);
        say('Loaded. Change anything and save again.');
      } else if (r.status === 404) {
        store(null);
        history.replaceState(null, '', location.pathname);
        say('That profile no longer exists, so you can make a new one.');
      } else {
        say('Couldn\'t reach the profile service. Try again in a moment.');
      }
    }, function () { say('Couldn\'t reach the profile service. Check your connection and try again.'); });
  }

  form.addEventListener('change', syncDependent);

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var built = buildProfile(readForm());
    showErrors(built.errors || []);
    if (built.errors) return;
    saveBtn.disabled = true;
    say('Saving…');
    var req = id ? call('PUT', '/api/profile/' + id, built.profile) : call('POST', '/api/profile', built.profile);
    req.then(function (r) {
      saveBtn.disabled = false;
      if (r.status === 200 || r.status === 201) {
        adopt(r.data);
        say(r.status === 201 ? 'Saved. Now subscribe below so the alerts reach your phone.' : 'Saved.');
        savedEl.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      } else if (r.status === 429) {
        say('That\'s a lot of new profiles from this connection. Try again in an hour.');
      } else if (r.data && r.data.errors) {
        say('');
        showErrors(r.data.errors);
      } else {
        say('Couldn\'t save. Try again in a moment.');
      }
    }, function () { saveBtn.disabled = false; say('Couldn\'t reach the profile service. Check your connection and try again.'); });
  });

  deleteBtn.addEventListener('click', function () {
    if (!id || !window.confirm('Delete your profile? You will stop getting alerts.')) return;
    call('DELETE', '/api/profile/' + id).then(function (r) {
      if (r.status === 204 || r.status === 404) {
        id = null; topic = null; store(null);
        history.replaceState(null, '', location.pathname);
        savedEl.hidden = true; deleteBtn.hidden = true;
        fillForm(valuesFromProfile(null));
        say('Deleted.');
      } else say('Couldn\'t delete it. Try again in a moment.');
    }, function () { say('Couldn\'t reach the profile service.'); });
  });

  function copy(text, button) {
    var done = function () { var was = button.textContent; button.textContent = 'Copied'; setTimeout(function () { button.textContent = was; }, 1500); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, function () {});
  }
  savedEl.querySelector('[data-pf-copy-link]').addEventListener('click', function (e) { copy(privateLink(), e.currentTarget); });
  savedEl.querySelector('[data-pf-copy-topic]').addEventListener('click', function (e) { copy(topic, e.currentTarget); });

  var testBtn = savedEl.querySelector('[data-pf-test]');
  testBtn.addEventListener('click', function () {
    testBtn.disabled = true;
    fetch('https://ntfy.sh/' + topic, { method: 'POST', body: 'If you can read this, your Swell Check alerts will reach you.', headers: { Title: 'Swell Check test' } })
      .then(function () { say('Sent. It should arrive in the ntfy app within a few seconds.'); },
            function () { say('Couldn\'t send the test. Check your connection.'); })
      .then(function () { testBtn.disabled = false; });
  });

  fillForm(valuesFromProfile(null));
  var fromLink = location.hash.slice(1);
  var existing = validId(fromLink) ? fromLink : (validId(stored()) ? stored() : null);
  rootEl.setAttribute('data-ready', '1');
  if (existing) load(existing);
  return api;
}));
