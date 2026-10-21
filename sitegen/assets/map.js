/* The map page: every break as a pin with its rating, and a card when you tap one.
 *
 * The page carries its own data (<script id="map-data">: slug, name, place, lat, lon, rating, band,
 * label, cond, when, href, thumb) and Leaflet (assets/vendor/leaflet) does the map. Tiles are the U.S.
 * Geological Survey's The National Map: free, no key, satellite imagery with place names or a topo map.
 * Text only ever goes in with textContent. The top half is plain functions so tests/test_map.py can run
 * them under Node.
 *
 * The address can name a break (map/#swamis) to open the map on it; the break pages link here that way.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.SwellMap = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var FAR_ZOOM = 12;     // below this the pins shrink to dots (and their click areas with them) so neighbours don't cover each other
  var GLYPH = { green: '✓', yellow: '!', orange: '▼', red: '✕' };
  var CHIP = { green: 'chip-good', yellow: 'chip-ok', orange: 'chip-serious', red: 'chip-poor' };

  var USGS = 'https://basemap.nationalmap.gov/arcgis/rest/services/';
  var TILES = {
    satellite: USGS + 'USGSImageryTopo/MapServer/tile/{z}/{y}/{x}',
    map: USGS + 'USGSTopo/MapServer/tile/{z}/{y}/{x}'
  };
  var NATIVE_ZOOM = 16;      // The National Map has no tiles past this; Leaflet enlarges them beyond it
  var SATELLITE_MIN_ZOOM = 11;   // its imagery has no ocean at wider zooms (white), so the topo map shows through there
  var ATTRIBUTION = 'Imagery and map data: <a href="https://www.usgs.gov/programs/national-geospatial-program/national-map" rel="noopener">USGS The National Map</a>';
  var MODE_KEY = 'swell-map-mode';

  /* "#swamis" -> "swamis", but only for a break we know. */
  function slugFromHash(hash, slugs) {
    var s = String(hash || '').replace(/^#/, '');
    try { s = decodeURIComponent(s); } catch (e) { /* leave it as typed */ }
    return slugs.indexOf(s) !== -1 ? s : null;
  }

  function isFar(zoom) { return zoom < FAR_ZOOM; }

  /* Pins that would sit on top of each other are shown as one badge. `items` are {slug, x, y, rating} with x and y in
     screen pixels at the current zoom; `w` and `h` are how close (px) two pins can be before they collide. Greedy,
     best-rated first, so the badge is led by the break you'd want to see. A pin joins at most one cluster, and the
     slugs in `keep` (the one with its card open) are never absorbed. Returns [[slug, ...], ...], each led by its best. */
  function cluster(items, w, h, keep) {
    keep = keep || [];
    var order = items.slice().sort(function (a, b) { return b.rating - a.rating; });
    var taken = {};
    var out = [];
    order.forEach(function (seed) {
      if (taken[seed.slug]) return;
      taken[seed.slug] = true;
      var group = [seed.slug];
      if (keep.indexOf(seed.slug) === -1) {
        order.forEach(function (o) {
          if (taken[o.slug] || keep.indexOf(o.slug) !== -1) return;
          if (Math.abs(o.x - seed.x) < w && Math.abs(o.y - seed.y) < h) { taken[o.slug] = true; group.push(o.slug); }
        });
      }
      out.push(group);
    });
    return out;
  }

  /* The size of the box one pin takes up, which is what decides whether two collide. */
  function pinBox(far) { return far ? { w: 38, h: 38 } : { w: 60, h: 28 }; }       // far: the size of a badge, the biggest thing drawn

  /* What a pin says out loud, for screen readers and the hover tooltip. */
  function pinLabel(p) { return p.name + ', ' + p.label + ', ' + Number(p.rating).toFixed(1) + ' out of 10'; }

  function validMode(m) { return m === 'satellite' || m === 'map' ? m : 'satellite'; }

  /* The label that appears when you hover or focus a pin: the break and how it rates, before you click. */
  function tipParts(p) {
    return { name: p.name, glyph: GLYPH[p.band] || '', rating: Number(p.rating).toFixed(1), label: p.label };
  }

  var api = { tipParts: tipParts, FAR_ZOOM: FAR_ZOOM, NATIVE_ZOOM: NATIVE_ZOOM, SATELLITE_MIN_ZOOM: SATELLITE_MIN_ZOOM, GLYPH: GLYPH, CHIP: CHIP, TILES: TILES, slugFromHash: slugFromHash,
              isFar: isFar, pinLabel: pinLabel, validMode: validMode, cluster: cluster, pinBox: pinBox };

  // ---------------------------------------------------------------------------- the page
  if (typeof document === 'undefined') return api;

  var mapEl = document.getElementById('map');
  var dataEl = document.getElementById('map-data');
  var wrap = document.querySelector('[data-map-root]');
  if (!mapEl || !dataEl || !wrap) return api;

  var points = [];
  try { points = JSON.parse(dataEl.textContent) || []; } catch (e) { points = []; }

  if (!window.L || !points.length) {
    wrap.setAttribute('data-failed', '1');       // the break list under the map is still there
    return api;
  }
  var L = window.L;

  var card = wrap.querySelector('[data-card]');
  var part = function (name) { return card.querySelector('[data-card-' + name + ']'); };

  var lats = points.map(function (p) { return p.lat; });
  var lons = points.map(function (p) { return p.lon; });
  var bounds = L.latLngBounds([Math.min.apply(null, lats), Math.min.apply(null, lons)],
                              [Math.max.apply(null, lats), Math.max.apply(null, lons)]);

  var map = L.map(mapEl, {
    minZoom: 9, maxZoom: 17, zoomSnap: 0.5, worldCopyJump: false, zoomControl: false,
    maxBounds: bounds.pad(0.9), maxBoundsViscosity: 0.85
  });
  L.control.zoom({ position: 'topright' }).addTo(map);
  map.attributionControl.setPrefix(false);
  var calm = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  // Keep the pins clear of the title, style switch and key that sit over the map's corners.
  var tight = window.innerWidth < 560;
  map.fitBounds(bounds, { paddingTopLeft: tight ? [24, 150] : [44, 44], paddingBottomRight: tight ? [24, 96] : [44, 44] });

  var tiles = null;
  var modeButtons = wrap.querySelectorAll('[data-mode]');
  function setMode(mode, remember) {
    mode = validMode(mode);
    if (tiles) map.removeLayer(tiles);
    var layers = [L.tileLayer(TILES.map, { attribution: ATTRIBUTION, maxZoom: 17, maxNativeZoom: NATIVE_ZOOM, zIndex: 1 })];
    if (mode === 'satellite') {
      layers.push(L.tileLayer(TILES.satellite, { maxZoom: 17, maxNativeZoom: NATIVE_ZOOM, minZoom: SATELLITE_MIN_ZOOM, zIndex: 2 }));
    }
    tiles = L.layerGroup(layers).addTo(map);
    wrap.setAttribute('data-mode', mode);
    Array.prototype.forEach.call(modeButtons, function (b) { b.setAttribute('aria-pressed', b.getAttribute('data-mode') === mode ? 'true' : 'false'); });
    if (remember) { try { localStorage.setItem(MODE_KEY, mode); } catch (e) { /* the choice just won't stick */ } }
  }
  Array.prototype.forEach.call(modeButtons, function (b) { b.addEventListener('click', function () { setMode(b.getAttribute('data-mode'), true); }); });
  var saved = null;
  try { saved = localStorage.getItem(MODE_KEY); } catch (e) { saved = null; }
  setMode(saved, false);

  function span(cls, text) {
    var s = document.createElement('span');
    s.className = cls;
    s.textContent = text;
    return s;
  }

  var markers = {};
  var current = null;

  points.forEach(function (p) {
    var pin = document.createElement('div');
    pin.className = 'pin pin-' + p.band;
    pin.appendChild(span('pin-ico', GLYPH[p.band] || ''));
    pin.appendChild(span('pin-num', Number(p.rating).toFixed(1)));
    var icon = L.divIcon({ html: pin, className: 'pin-wrap', iconSize: [62, 30], iconAnchor: [31, 15] });
    var m = L.marker([p.lat, p.lon], { icon: icon, keyboard: true, riseOnHover: true, zIndexOffset: Math.round(p.rating * 100) });
    m.on('click', function () { select(p.slug, true); });
    m.addTo(map);

    // The label on hover (and on keyboard focus). It replaces the browser's own delayed tooltip.
    var t = tipParts(p);
    var tip = document.createElement('span');
    tip.className = 'tip-in';
    var name = document.createElement('strong');
    name.textContent = t.name;
    var rate = span('tip-rate tip-' + p.band, t.glyph + ' ' + t.rating + ' · ' + t.label);
    tip.appendChild(name);
    tip.appendChild(rate);
    m.bindTooltip(tip, { direction: 'top', offset: [0, -14], opacity: 1, className: 'pin-tip' });
    var el = m.getElement();
    if (el) {
      el.setAttribute('aria-label', pinLabel(p));
      el.addEventListener('focus', function () { m.openTooltip(); });
      el.addEventListener('blur', function () { m.closeTooltip(); });
    }
    markers[p.slug] = { marker: m, pin: pin, point: p };
  });

  // Nearby pins merge into one numbered badge; tapping it zooms in until they separate.
  var clusterLayer = L.layerGroup().addTo(map);
  function refreshClusters() {
    clusterLayer.clearLayers();
    var zoom = map.getZoom();
    var box = pinBox(isFar(zoom));
    var items = points.map(function (p) {
      var px = map.project([p.lat, p.lon], zoom);
      return { slug: p.slug, x: px.x, y: px.y, rating: p.rating };
    });
    var groups = cluster(items, box.w, box.h, current ? [current] : []);
    groups.forEach(function (slugs) {
      var single = slugs.length === 1;
      slugs.forEach(function (s) { var el = markers[s].marker.getElement(); if (el) el.style.display = single ? '' : 'none'; });
      if (!single) addBadge(slugs);
    });
  }

  function addBadge(slugs) {
    var members = slugs.map(function (s) { return markers[s].point; });      // best-rated first
    var best = members[0];
    var lat = 0, lon = 0;
    members.forEach(function (m) { lat += m.lat; lon += m.lon; });
    var at = [lat / members.length, lon / members.length];
    var badge = document.createElement('div');
    badge.className = 'pin pin-cluster pin-' + best.band;
    badge.appendChild(span('pin-num', String(members.length)));
    var icon = L.divIcon({ html: badge, className: 'cluster-wrap', iconSize: [38, 38], iconAnchor: [19, 19] });
    var label = members.length + ' breaks here, best is ' + pinLabel(best);
    var m = L.marker(at, { icon: icon, keyboard: true, riseOnHover: true, zIndexOffset: 5000 + Math.round(best.rating * 100) });
    var tip = document.createElement('span');
    tip.className = 'tip-in';
    var head = document.createElement('strong');
    head.textContent = members.length + ' breaks, tap to zoom in';
    tip.appendChild(head);
    members.slice(0, 6).forEach(function (p) { tip.appendChild(span('tip-rate', GLYPH[p.band] + ' ' + Number(p.rating).toFixed(1) + '  ' + p.name)); });
    if (members.length > 6) tip.appendChild(span('tip-rate', '+' + (members.length - 6) + ' more'));
    m.bindTooltip(tip, { direction: 'top', offset: [0, -16], opacity: 1, className: 'pin-tip' });
    m.on('click', function () {
      var b = L.latLngBounds(members.map(function (p) { return [p.lat, p.lon]; }));
      map.flyToBounds(b, { padding: [70, 70], maxZoom: 16, duration: calm ? 0 : 0.5 });
    });
    m.addTo(clusterLayer);
    var el = m.getElement();
    if (el) {
      el.setAttribute('aria-label', label);
      el.addEventListener('focus', function () { m.openTooltip(); });
      el.addEventListener('blur', function () { m.closeTooltip(); });
    }
  }

  function farClass() { wrap.classList.toggle('map-far', isFar(map.getZoom())); }
  map.on('zoomend', function () { farClass(); refreshClusters(); });
  farClass();

  function fillCard(p) {
    part('name').textContent = p.name;
    part('place').textContent = p.place;
    part('cond').textContent = p.cond;
    part('when').textContent = p.when;
    var link = part('link');
    link.setAttribute('href', p.href);
    link.textContent = 'Open ' + p.name;
    var chip = part('chip');
    chip.className = 'chip chip-pill ' + (CHIP[p.band] || '');
    chip.textContent = '';
    chip.appendChild(span('chip-ico', GLYPH[p.band] || ''));
    chip.appendChild(span('chip-num', Number(p.rating).toFixed(1)));
    chip.appendChild(span('chip-lbl', p.label));
    chip.querySelector('.chip-ico').setAttribute('aria-hidden', 'true');
    var photo = part('photo');
    if (p.thumb) { photo.setAttribute('src', p.thumb); photo.hidden = false; } else { photo.removeAttribute('src'); photo.hidden = true; }
  }

  function select(slug, move) {
    var entry = markers[slug];
    if (!entry) return;
    if (current && markers[current]) markers[current].pin.classList.remove('is-on');
    current = slug;
    entry.pin.classList.add('is-on');
    refreshClusters();
    fillCard(entry.point);
    card.hidden = false;
    wrap.classList.add('has-card');
    if (history.replaceState) history.replaceState(null, '', '#' + slug);
    if (move) {
      var target = Math.max(map.getZoom(), 12);
      map.flyTo(entry.marker.getLatLng(), target, { duration: calm ? 0 : 0.6 });
      // On a phone the card covers the lower part of the map: nudge the pin up into the clear part.
      if (window.innerWidth < 760) map.once('moveend', function () { map.panBy([0, Math.round(card.offsetHeight / 2)], { animate: !calm }); });
    }
  }

  function close() {
    if (current && markers[current]) markers[current].pin.classList.remove('is-on');
    current = null;
    refreshClusters();
    card.hidden = true;
    wrap.classList.remove('has-card');
    if (history.replaceState && location.hash) history.replaceState(null, '', location.pathname + location.search);
  }

  part('close').addEventListener('click', close);
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
  map.on('click', close);

  var slugs = points.map(function (p) { return p.slug; });
  function fromHash() {
    var s = slugFromHash(location.hash, slugs);
    if (s && s !== current) select(s, true);
  }
  window.addEventListener('hashchange', fromHash);
  wrap.setAttribute('data-ready', '1');
  refreshClusters();
  fromHash();

  return api;
}));
