'use client';

import { useEffect, useRef, useState } from 'react';
import 'mapbox-gl/dist/mapbox-gl.css';
import { MAPBOX_TOKEN } from '../_lib/mapbox';

const STYLES = { dark: 'mapbox://styles/mapbox/dark-v11', light: 'mapbox://styles/mapbox/light-v11' };

const isDark = () => document.documentElement.classList.contains('dark');
const ink = () => getComputedStyle(document.documentElement).getPropertyValue('--fg').trim();
const mute = () => getComputedStyle(document.documentElement).getPropertyValue('--mute').trim();
const paper = () => getComputedStyle(document.documentElement).getPropertyValue('--bg').trim();

function collection(pieces, monitored) {
  return {
    type: 'FeatureCollection',
    features: pieces
      .filter((p) => p.monitored === monitored)
      .map((p) => ({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: p.coords } })),
  };
}

function draw(map, { pieces, line }) {
  for (const id of ['route-on', 'route-off', 'ends']) {
    if (map.getLayer(id)) map.removeLayer(id);
    if (map.getSource(id)) map.removeSource(id);
  }
  map.addSource('route-off', { type: 'geojson', data: collection(pieces, false) });
  map.addSource('route-on', { type: 'geojson', data: collection(pieces, true) });
  map.addSource('ends', {
    type: 'geojson',
    data: {
      type: 'FeatureCollection',
      features: [line[0], line.at(-1)].map((c) => ({
        type: 'Feature',
        properties: {},
        geometry: { type: 'Point', coordinates: c },
      })),
    },
  });
  map.addLayer({
    id: 'route-off',
    type: 'line',
    source: 'route-off',
    layout: { 'line-cap': 'butt', 'line-join': 'round' },
    paint: { 'line-color': mute(), 'line-width': 3, 'line-dasharray': [1.5, 1.5] },
  });
  map.addLayer({
    id: 'route-on',
    type: 'line',
    source: 'route-on',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': ink(), 'line-width': 5 },
  });
  map.addLayer({
    id: 'ends',
    type: 'circle',
    source: 'ends',
    paint: { 'circle-radius': 6, 'circle-color': ink(), 'circle-stroke-color': paper(), 'circle-stroke-width': 2 },
  });
}

export default function RouteMap({ pieces, line }) {
  const container = useRef(null);
  const mapRef = useRef(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let observer;

    (async () => {
      try {
        const { default: mapboxgl } = await import('mapbox-gl');
        if (cancelled || !container.current) return;
        mapboxgl.accessToken = MAPBOX_TOKEN;
        const map = new mapboxgl.Map({
          container: container.current,
          style: isDark() ? STYLES.dark : STYLES.light,
          bounds: boundsOf(line),
          fitBoundsOptions: { padding: 48 },
          cooperativeGestures: true,
          dragRotate: false,
          pitchWithRotate: false,
        });
        map.touchZoomRotate.disableRotation();
        mapRef.current = map;
        map.on('style.load', () => draw(map, { pieces, line }));
        map.on('error', (e) => {
          if (e?.error?.status === 401) setFailed(true);
        });

        observer = new MutationObserver(() => map.setStyle(isDark() ? STYLES.dark : STYLES.light));
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();

    return () => {
      cancelled = true;
      observer?.disconnect();
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, [pieces, line]);

  if (failed) return <p className="t-note">The map could not load. The forecast above is unaffected.</p>;

  return (
    <figure className="t-map">
      <div ref={container} className="t-map-canvas" role="img" aria-label="Map of your route" />
      <figcaption className="mono t-legend">
        <span>Monitored corridor</span>
        <span className="is-dashed">Not monitored</span>
      </figcaption>
    </figure>
  );
}

function boundsOf(line) {
  let [w, s, e, n] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const [lon, lat] of line) {
    w = Math.min(w, lon);
    e = Math.max(e, lon);
    s = Math.min(s, lat);
    n = Math.max(n, lat);
  }
  return [
    [w, s],
    [e, n],
  ];
}
