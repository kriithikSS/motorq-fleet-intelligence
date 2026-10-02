'use client';

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';

interface TelemetryPoint { ts: string; speed_kmh: number; soc_pct: number | null; }
interface VehicleDetail {
  vin: string; make: string; model: string; year: number;
  region: string; vehicle_type: string; oem: string;
  odo_km: number; last_seen: string;
  failure_prob_7d: number; recommended_action: string;
}

function generateTelemetry(count = 48): TelemetryPoint[] {
  return Array.from({ length: count }, (_, i) => ({
    ts: new Date(Date.now() - (count - i) * 30 * 60 * 1000).toISOString(),
    speed_kmh: Math.max(0, 60 + Math.sin(i * 0.5) * 30 + (Math.random() - 0.5) * 20),
    soc_pct: Math.max(5, 80 - i * 1.2 + (Math.random() - 0.5) * 5),
  }));
}

export default function VehicleDetailPage() {
  const { vin } = useParams() as { vin: string };
  const [vehicle, setVehicle] = useState<VehicleDetail | null>(null);
  const [telemetry, setTelemetry] = useState<TelemetryPoint[]>([]);

  useEffect(() => {
    // In production: fetch from /api/vehicles/{vin}
    setVehicle({
      vin: vin || '1HGCM82633A004352',
      make: 'Ford', model: 'F-150', year: 2022,
      region: 'Mumbai', vehicle_type: 'ICE', oem: 'Ford Motor Company',
      odo_km: 18_234, last_seen: new Date().toISOString(),
      failure_prob_7d: 0.91, recommended_action: 'URGENT: Remove from service immediately.',
    });
    setTelemetry(generateTelemetry(48));
  }, [vin]);

  if (!vehicle) return <div style={{ padding: 40, color: 'var(--text-muted)' }}>Loading…</div>;

  const maxSpeed = Math.max(...telemetry.map(t => t.speed_kmh));
  const avgSpeed = telemetry.reduce((s, t) => s + t.speed_kmh, 0) / telemetry.length;

  return (
    <div style={{ padding: 24 }}>
      {/* Back */}
      <a href="/" style={{ color: 'var(--accent-blue)', fontSize: 13, textDecoration: 'none', display: 'inline-block', marginBottom: 20 }}>
        ← Back to Fleet Overview
      </a>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 24 }}>
        {/* Vehicle Info Card */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">🚗 Vehicle Information</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            {[
              ['VIN', vehicle.vin],
              ['Make / Model', `${vehicle.make} ${vehicle.model}`],
              ['Year', vehicle.year],
              ['Type', vehicle.vehicle_type],
              ['Region', vehicle.region],
              ['Odometer', `${vehicle.odo_km.toLocaleString()} km`],
              ['OEM', vehicle.oem],
              ['Last Seen', new Date(vehicle.last_seen).toLocaleTimeString()],
            ].map(([label, value]) => (
              <div key={label as string}>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>{label}</div>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{value}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Maintenance Risk Card */}
        <div className="card" style={{ borderColor: vehicle.failure_prob_7d > 0.8 ? 'rgba(239,68,68,0.4)' : 'var(--border)' }}>
          <div className="card-header">
            <span className="card-title">🔧 Maintenance Risk</span>
          </div>
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 48, fontWeight: 800, color: vehicle.failure_prob_7d > 0.8 ? '#ef4444' : '#f59e0b', marginBottom: 4 }}>
              {(vehicle.failure_prob_7d * 100).toFixed(0)}%
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>7-day breakdown probability</div>
          </div>
          <div className="progress-bar" style={{ marginBottom: 12 }}>
            <div className="progress-fill" style={{ width: `${vehicle.failure_prob_7d * 100}%`, background: vehicle.failure_prob_7d > 0.8 ? '#ef4444' : '#f59e0b' }} />
          </div>
          <div style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8, padding: '10px 12px', fontSize: 12, color: '#f87171' }}>
            {vehicle.recommended_action}
          </div>
        </div>
      </div>

      {/* Speed Chart */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-header">
          <span className="card-title">📈 Speed History (last 24h)</span>
          <div style={{ display: 'flex', gap: 16, fontSize: 12, color: 'var(--text-secondary)' }}>
            <span>Avg: <b style={{ color: 'var(--text-primary)' }}>{avgSpeed.toFixed(1)} km/h</b></span>
            <span>Max: <b style={{ color: '#f59e0b' }}>{maxSpeed.toFixed(1)} km/h</b></span>
          </div>
        </div>
        {/* Simple SVG sparkline */}
        <svg width="100%" height="120" style={{ overflow: 'visible' }}>
          {(() => {
            const pts = telemetry;
            const w = 800;
            const h = 100;
            const xs = pts.map((_, i) => (i / (pts.length - 1)) * w);
            const ys = pts.map(p => h - (p.speed_kmh / 150) * h);
            const path = pts.map((_, i) => `${i === 0 ? 'M' : 'L'} ${xs[i]} ${ys[i]}`).join(' ');
            const fill = pts.map((_, i) => `${i === 0 ? 'M' : 'L'} ${xs[i]} ${ys[i]}`).join(' ') + ` L ${w} ${h} L 0 ${h} Z`;
            return (
              <g transform="translate(0,10)">
                <path d={fill} fill="rgba(59,130,246,0.1)" />
                <path d={path} fill="none" stroke="#3b82f6" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                {pts.map((p, i) => p.speed_kmh > 90 && (
                  <circle key={i} cx={xs[i]} cy={ys[i]} r={3} fill="#f59e0b" />
                ))}
              </g>
            );
          })()}
        </svg>
      </div>

      {/* SoC Chart */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">🔋 State of Charge (last 24h)</span>
          <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
            Current: <b style={{ color: 'var(--accent-green)' }}>{telemetry[telemetry.length - 1]?.soc_pct?.toFixed(1)}%</b>
          </span>
        </div>
        <svg width="100%" height="80" style={{ overflow: 'visible' }}>
          {(() => {
            const pts = telemetry.filter(t => t.soc_pct !== null);
            if (!pts.length) return null;
            const w = 800; const h = 60;
            const xs = pts.map((_, i) => (i / (pts.length - 1)) * w);
            const ys = pts.map(p => h - ((p.soc_pct ?? 0) / 100) * h);
            const path = pts.map((_, i) => `${i === 0 ? 'M' : 'L'} ${xs[i]} ${ys[i]}`).join(' ');
            const fill = path + ` L ${w} ${h} L 0 ${h} Z`;
            return (
              <g transform="translate(0,10)">
                <path d={fill} fill="rgba(16,185,129,0.1)" />
                <path d={path} fill="none" stroke="#10b981" strokeWidth="2" strokeLinecap="round" />
              </g>
            );
          })()}
        </svg>
      </div>
    </div>
  );
}
