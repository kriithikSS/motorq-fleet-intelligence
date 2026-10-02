'use client';

import 'leaflet/dist/leaflet.css';
import { useEffect, useRef, useState } from 'react';

interface Vehicle {
  vin: string; lat: number; lon: number;
  speed_kmh: number; soc_pct: number | null; alert: boolean;
}

const REGIONS: [number, number][] = [
  [19.076, 72.877], [28.704, 77.102], [12.971, 77.594],
  [13.083, 80.270], [22.572, 88.364], [17.385, 78.487],
  [23.022, 72.571], [18.520, 73.856],
];

function generateVehicles(count = 500): Vehicle[] {
  return Array.from({ length: count }, (_, i) => {
    const [bLat, bLon] = REGIONS[i % REGIONS.length];
    return {
      vin: `VIN${String(i).padStart(12, '0')}`,
      lat: bLat + (Math.random() - 0.5) * 1.4,
      lon: bLon + (Math.random() - 0.5) * 1.4,
      speed_kmh: Math.random() * 110,
      soc_pct: Math.random() > 0.3 ? Math.random() * 100 : null,
      alert: Math.random() < 0.05,
    };
  });
}

export default function FleetMapPage() {
  const mapRef        = useRef<HTMLDivElement>(null);
  const leafletMapRef = useRef<any>(null);

  // Keep vehicles + counts in state, populated client-side only
  // to avoid SSR/client hydration mismatch from Math.random()
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [alertCount, setAlertCount] = useState(0);
  const [mounted, setMounted] = useState(false);

  // Generate data only on the client
  useEffect(() => {
    const v = generateVehicles(500);
    setVehicles(v);
    setAlertCount(v.filter(x => x.alert).length);
    setMounted(true);
  }, []);

  // Init map once vehicles are ready
  useEffect(() => {
    if (!mounted || !mapRef.current || vehicles.length === 0) return;
    if ((mapRef.current as any)._leaflet_id) return;

    import('leaflet').then((mod) => {
      const L = mod.default ?? mod;
      if (!mapRef.current || (mapRef.current as any)._leaflet_id) return;

      delete (L.Icon.Default.prototype as any)._getIconUrl;
      L.Icon.Default.mergeOptions({
        iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
        iconUrl:       'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
        shadowUrl:     'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
      });

      const map = L.map(mapRef.current, {
        center: [20.5937, 78.9629],
        zoom: 5,
        zoomControl: true,
        preferCanvas: true,
      });
      leafletMapRef.current = map;

      // Free OSM tiles + CSS dark filter (no API key needed)
      const tileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 19,
      }).addTo(map);

      // Apply dark invert filter to the tile layer container
      tileLayer.on('tileload', () => {
        const container = map.getPane('tilePane');
        if (container) {
          (container as HTMLElement).style.filter = 'invert(1) hue-rotate(180deg) brightness(0.85) contrast(0.9) saturate(0.7)';
        }
      });

      const normalIcon = L.divIcon({
        className: '',
        html: '<div style="width:8px;height:8px;border-radius:50%;background:#3b82f6;border:1.5px solid #93c5fd;box-shadow:0 0 6px #3b82f6"></div>',
        iconSize: [8, 8], iconAnchor: [4, 4],
      });
      const alertIcon = L.divIcon({
        className: '',
        html: '<div style="width:11px;height:11px;border-radius:50%;background:#ef4444;border:1.5px solid #fca5a5;box-shadow:0 0 10px #ef4444"></div>',
        iconSize: [11, 11], iconAnchor: [5, 5],
      });

      vehicles.forEach(v => {
        L.marker([v.lat, v.lon], { icon: v.alert ? alertIcon : normalIcon })
          .addTo(map)
          .bindPopup(`
            <div style="font-family:'Courier New',monospace;font-size:11px;
                        background:#111e38;color:#f0f4ff;padding:10px 12px;
                        border-radius:8px;min-width:190px;
                        border:1px solid rgba(59,130,246,0.3)">
              <div style="color:#60a5fa;font-weight:700;margin-bottom:6px">${v.vin.slice(0, 14)}…</div>
              <div>Speed: <b>${v.speed_kmh.toFixed(1)} km/h</b></div>
              ${v.soc_pct !== null ? `<div>Battery SoC: <b>${v.soc_pct.toFixed(0)}%</b></div>` : ''}
              <div style="margin-top:6px;font-weight:600;${v.alert ? 'color:#f87171' : 'color:#4ade80'}">
                ${v.alert ? '▲ ACTIVE ALERT' : '✓ Normal'}
              </div>
            </div>`, { className: '' });
      });
    });

    return () => {
      if (leafletMapRef.current) {
        leafletMapRef.current.remove();
        leafletMapRef.current = null;
      }
    };
  }, [mounted, vehicles]);

  return (
    <div style={{ display:'flex', flexDirection:'column', height:'100vh', background:'#060b18' }}>
      {/* Header */}
      <div style={{
        display:'flex', alignItems:'center', justifyContent:'space-between',
        padding:'12px 24px', flexShrink: 0,
        background:'#0c1428', borderBottom:'1px solid rgba(255,255,255,0.07)',
      }}>
        <div>
          <div style={{ display:'flex', alignItems:'center', gap:10 }}>
            <a href="/" style={{ fontSize:12, color:'#4e6080', textDecoration:'none' }}>← Dashboard</a>
            <span style={{ color:'#2a3a55' }}>|</span>
            <span style={{ fontSize:15, fontWeight:700, color:'#f0f4ff' }}>Real-Time Fleet Map</span>
          </div>
          <div style={{ fontSize:12, color:'#4e6080', marginTop:2 }}>
            Live positions · {mounted ? vehicles.length.toLocaleString() : '…'} vehicles · 8 Indian cities
          </div>
        </div>

        {mounted && (
          <div style={{ display:'flex', gap:20, alignItems:'center' }}>
            <div style={{ display:'flex', alignItems:'center', gap:7, fontSize:12, color:'#93c5fd' }}>
              <div style={{ width:8, height:8, borderRadius:'50%', background:'#3b82f6', boxShadow:'0 0 6px #3b82f6' }} />
              {vehicles.length - alertCount} Normal
            </div>
            <div style={{ display:'flex', alignItems:'center', gap:7, fontSize:12, color:'#f87171' }}>
              <div style={{ width:10, height:10, borderRadius:'50%', background:'#ef4444', boxShadow:'0 0 8px #ef4444' }} />
              {alertCount} Alerts
            </div>
            <div style={{
              display:'flex', alignItems:'center', gap:7, padding:'4px 12px',
              background:'rgba(34,197,94,0.12)', border:'1px solid rgba(34,197,94,0.25)',
              borderRadius:20, fontSize:11, fontWeight:600, color:'#4ade80',
            }}>
              <div style={{ width:6, height:6, borderRadius:'50%', background:'#22c55e' }} />
              Live
            </div>
          </div>
        )}
      </div>

      {/* Map */}
      <div ref={mapRef} style={{ flex:1, minHeight:0 }} />
    </div>
  );
}
