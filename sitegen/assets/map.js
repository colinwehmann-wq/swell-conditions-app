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

  var FAR_ZOOM = 11;     // below this the pins shrink to dots so the coast doesn't become a pile
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

  /* What a pin says out loud, for screen readers and the hover tooltip. */
  function pinLabel(p) { return p.name + ', ' + p.label + ', ' + Number(p.rating).toFixed(1) + ' out of 10'; }

  function validMode(m) { return m === 'satellite' || m === 'map' ? m : 'satellite'; }

  var api = { FAR_ZOOM: FAR_ZOOM, NATIVE_ZOOM: NATIVE_ZOOM, SATELLITE_MIN_ZOOM: SATELLITE_MIN_ZOOM, GLYPH: GLYPH, CHIP: CHIP, TILES: TILES, slugFromHash: slugFromHash,
              isFar: isFar, pinLabel: pinLabel, validMode: validMode };

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
  map.fitBounds(bounds, { padding: [44, 44] });

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
    var m = L.marker([p.lat, p.lon], { icon: icon, title: pinLabel(p), alt: pinLabel(p), keyboard: true, riseOnHover: true,
                                       zIndexOffset: Math.round(p.rating * 100) });
    m.on('click', function () { select(p.slug, true); });
    m.addTo(map);
    markers[p.slug] = { marker: m, pin: pin, point: p };
  });

  function farClass() { wrap.classList.toggle('map-far', isFar(map.getZoom())); }
  map.on('zoomend', farClass);
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
  fromHash();

  return api;
}));
