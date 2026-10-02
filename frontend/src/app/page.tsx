'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import {
  api,
  FALLBACK_STATS, FALLBACK_PREDICTIONS, FALLBACK_DRIVERS,
  type Alert,
  type FleetStats, type MaintenancePrediction, type Driver,
} from '../lib/api';

// Static fallback alerts (fixed timestamps avoid SSR/client Date.now() mismatch)
const FALLBACK_ALERTS: Alert[] = [
  { alert_id:'1', vin:'1HGCM82633A004352', alert_type:'CRITICAL_DTC',     severity:'critical', event_ts:'2026-10-02T03:00:00Z', dtc_code:'P0300' },
  { alert_id:'2', vin:'1FTFW1E55NFA12345', alert_type:'LOW_BATTERY',      severity:'high',     event_ts:'2026-10-02T02:58:00Z' },
  { alert_id:'3', vin:'WVW1234567890ABCD', alert_type:'HARSH_BRAKE',      severity:'medium',   event_ts:'2026-10-02T02:55:00Z' },
  { alert_id:'4', vin:'JHM1234567890ABCD', alert_type:'BATTERY_OVERHEAT', severity:'critical', event_ts:'2026-10-02T02:59:00Z' },
  { alert_id:'5', vin:'YV1KS9143P1234567', alert_type:'GEO_FENCE_BREACH', severity:'medium',   event_ts:'2026-10-02T02:45:00Z' },
];

// ── SVG Icons ───────────────────────────────────────────────────────────────
const Icon = {
  Grid:   () => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="1" y="1" width="6" height="6" rx="1"/><rect x="9" y="1" width="6" height="6" rx="1"/><rect x="1" y="9" width="6" height="6" rx="1"/><rect x="9" y="9" width="6" height="6" rx="1"/></svg>,
  Map:    () => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><polygon points="1,3 6,1 10,3 15,1 15,13 10,15 6,13 1,15"/><line x1="6" y1="1" x2="6" y2="13"/><line x1="10" y1="3" x2="10" y2="15"/></svg>,
  Bell:   () => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M8 1a5 5 0 015 5v3l1.5 2.5H1.5L3 9V6a5 5 0 015-5z"/><path d="M6.5 13.5a1.5 1.5 0 003 0"/></svg>,
  Wrench: () => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M13.5 2.5a3 3 0 00-4 4L3 13a1.4 1.4 0 002 2l6.5-6.5a3 3 0 004-4l-2 2-1.5-1.5 2-2z"/></svg>,
  User:   () => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="8" cy="5" r="3"/><path d="M2 14c0-3.3 2.7-6 6-6s6 2.7 6 6"/></svg>,
  Bot:    () => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="2" y="5" width="12" height="9" rx="2"/><circle cx="5.5" cy="9.5" r="1"/><circle cx="10.5" cy="9.5" r="1"/><path d="M6 13h4M8 5V2M6 2h4"/></svg>,
  Cpu:    () => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="4" y="4" width="8" height="8" rx="1"/><path d="M6 4V2M8 4V2M10 4V2M6 14v-2M8 14v-2M10 14v-2M4 6H2M4 8H2M4 10H2M14 6h-2M14 8h-2M14 10h-2"/></svg>,
  Zap:    () => <svg viewBox="0 0 16 16" fill="currentColor"><path d="M9.5 1L3 9h5.5L6.5 15L14 7H8.5L9.5 1z"/></svg>,
  Send:   () => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M14 2L1 6.5l5 2 2 5L14 2zM6 8.5l3-3"/></svg>,
  Check:  () => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2"><path d="M2 8l4 4 8-8"/></svg>,
  Refresh:() => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M13.5 8A5.5 5.5 0 112.5 5.5"/><path d="M2.5 2v3.5H6"/></svg>,
  ArrowRight:()=><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M3 8h10M9 4l4 4-4 4"/></svg>,
};

// ── Small helpers ───────────────────────────────────────────────────────────
function formatTime(ts: string) {
  const diff = Date.now() - new Date(ts).getTime();
  if (diff < 60000)   return `${Math.floor(diff / 1000)}s ago`;
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  return new Date(ts).toLocaleTimeString();
}

function SeverityBadge({ severity }: { severity: string }) {
  const dot = ({ critical:'#f87171', high:'#fbbf24', medium:'#60a5fa', low:'#4ade80' } as any)[severity] ?? '#888';
  return (
    <span className={`badge badge-${severity}`}>
      <span className="badge-dot" style={{ background: dot }} />
      {severity.toUpperCase()}
    </span>
  );
}

function RiskBar({ prob }: { prob: number }) {
  const color = prob > 0.8 ? 'var(--red)' : prob > 0.6 ? 'var(--amber)' : 'var(--blue)';
  return (
    <div style={{ display:'flex', alignItems:'center', gap:8 }}>
      <div className="progress-track">
        <div className="progress-fill" style={{ width:`${prob*100}%`, background: color }} />
      </div>
      <span style={{ fontSize:12, fontWeight:700, color }}>{(prob*100).toFixed(0)}%</span>
    </div>
  );
}

function ScoreBar({ score }: { score: number }) {
  const color = score >= 80 ? 'var(--green)' : score >= 60 ? 'var(--amber)' : 'var(--red)';
  return (
    <div style={{ display:'flex', alignItems:'center', gap:8 }}>
      <div className="progress-track" style={{ width:70 }}>
        <div className="progress-fill" style={{ width:`${score}%`, background: color }} />
      </div>
      <span style={{ fontSize:12, fontWeight:700, color }}>{score.toFixed(1)}</span>
    </div>
  );
}

function Sparkline({ color }: { color: string }) {
  const bars = [40,55,45,65,50,70,60,80,65,90,75,85];
  return (
    <div className="sparkline">
      {bars.map((h,i) => <div key={i} className="spark-bar" style={{ height:`${h}%`, background:color }} />)}
    </div>
  );
}

// ── Architecture tab ────────────────────────────────────────────────────────
function ArchitectureTab() {
  const nodes = [
    { label:'Vehicle', sub:'MQTT/HTTP', bg:'rgba(59,130,246,0.15)', border:'rgba(59,130,246,0.3)', color:'#3b82f6', icon:<Icon.Zap/> },
    { label:'EMQX',    sub:'Broker',   bg:'rgba(6,182,212,0.15)',  border:'rgba(6,182,212,0.3)',  color:'#06b6d4', icon:<Icon.Cpu/> },
    { label:'Kafka',   sub:'12 part.', bg:'rgba(245,158,11,0.15)', border:'rgba(245,158,11,0.3)', color:'#f59e0b', icon:<Icon.Cpu/> },
    { label:'Spark',   sub:'Stream',   bg:'rgba(239,68,68,0.15)',  border:'rgba(239,68,68,0.3)',  color:'#ef4444', icon:<Icon.Cpu/> },
    { label:'TimescaleDB',sub:'Series',bg:'rgba(34,197,94,0.15)', border:'rgba(34,197,94,0.3)',  color:'#22c55e', icon:<Icon.Grid/>},
    { label:'MongoDB', sub:'State',    bg:'rgba(168,85,247,0.15)',border:'rgba(168,85,247,0.3)', color:'#a855f7', icon:<Icon.Grid/>},
    { label:'Redis',   sub:'Cache',    bg:'rgba(239,68,68,0.15)',  border:'rgba(239,68,68,0.3)',  color:'#ef4444', icon:<Icon.Cpu/> },
    { label:'API GW',  sub:'FastAPI',  bg:'rgba(59,130,246,0.15)', border:'rgba(59,130,246,0.3)', color:'#3b82f6', icon:<Icon.Cpu/> },
  ];
  return (
    <div>
      <div className="page-header"><div className="page-title">System Architecture</div><div className="page-subtitle">Polyglot data pipeline — 100K vehicles · 1M events/min</div></div>
      <div className="card mb-16">
        <div className="card-header"><span className="card-title">Data Ingestion Pipeline</span><span className="badge badge-low" style={{ fontSize:9 }}>LIVE FLOW</span></div>
        <div className="pipeline">
          {nodes.map((n,i) => (
            <div key={n.label} style={{ display:'flex', alignItems:'center' }}>
              <div className="pipeline-node">
                <div className="pipeline-icon-wrap" style={{ background:n.bg, borderColor:n.border }}>
                  <div style={{ width:22, height:22, color:n.color }}>{n.icon}</div>
                </div>
                <div className="pipeline-label">{n.label}</div>
                <div className="pipeline-sublabel">{n.sub}</div>
              </div>
              {i < nodes.length-1 && <div className="pipeline-arrow"><div style={{ width:14, height:14, color:'var(--text-muted)' }}><Icon.ArrowRight/></div></div>}
            </div>
          ))}
        </div>
      </div>
      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:14 }}>
        <div className="card">
          <div className="card-header"><span className="card-title">Data Structure Decisions</span></div>
          {[
            { name:'Vehicle state cache', ds:'Hash Map (Redis)',   why:'O(1) lookup by VIN, 15s TTL' },
            { name:'Alert deduplication', ds:'Bloom Filter',       why:'Probabilistic, memory-efficient' },
            { name:'Fleet leaderboard',   ds:'Sorted Set (Redis)', why:'O(log N) rank queries' },
            { name:'Geofence detection',  ds:'R-Tree index',       why:'Spatial range queries' },
            { name:'Time-series queries', ds:'TimescaleDB chunks', why:'Partitioned by time, continuous aggregates' },
            { name:'VIN lookup index',    ds:'B-Tree (Postgres)',  why:'O(log N), range scans' },
          ].map(r => (
            <div key={r.name} style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:8, padding:'8px 0', borderBottom:'1px solid var(--border)' }}>
              <div><div style={{ fontSize:12, fontWeight:600 }}>{r.name}</div><div style={{ fontSize:11, color:'var(--text-muted)' }}>{r.why}</div></div>
              <div style={{ display:'flex', alignItems:'center' }}><span className="badge badge-medium mono">{r.ds}</span></div>
            </div>
          ))}
        </div>
        <div className="card">
          <div className="card-header"><span className="card-title">Algorithm Complexity</span></div>
          {[
            { op:'Fleet list (paginated)',    big:'O(log N + k)', impl:'Keyset cursor pagination' },
            { op:'Alert dedup check',         big:'O(1)',         impl:'Bloom filter on event hash' },
            { op:'Driver score computation',  big:'O(n)',         impl:'Streaming aggregation per trip' },
            { op:'Maintenance prediction',    big:'O(F·n)',       impl:'XGBoost, F features, batch nightly' },
            { op:'Top-K at-risk vehicles',    big:'O(n log k)',   impl:'Min-heap, k=1000' },
            { op:'Geo-fence breach',          big:'O(log n)',     impl:'R-Tree range intersection' },
          ].map(r => (
            <div key={r.op} style={{ display:'grid', gridTemplateColumns:'1fr auto', gap:8, padding:'8px 0', borderBottom:'1px solid var(--border)', alignItems:'center' }}>
              <div><div style={{ fontSize:12, fontWeight:600 }}>{r.op}</div><div style={{ fontSize:11, color:'var(--text-muted)' }}>{r.impl}</div></div>
              <span className="badge badge-critical mono">{r.big}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Main Dashboard ──────────────────────────────────────────────────────────
type Tab = 'overview' | 'alerts' | 'maintenance' | 'drivers' | 'agent' | 'architecture';
interface ChatMessage { role: 'user' | 'ai'; content: string; }

const SUGGESTIONS = [
  'Which vehicles will break down this week?',
  'Show me critical alerts from today',
  'Who are my worst performing drivers?',
  'How many EVs have low battery?',
];

export default function Dashboard() {
  const [activeTab, setActiveTab] = useState<Tab>('overview');

  // ── API data state ──
  const [stats,       setStats]       = useState<FleetStats>(FALLBACK_STATS);
  const [alerts,      setAlerts]      = useState<Alert[]>(FALLBACK_ALERTS);
  const [predictions, setPredictions] = useState<MaintenancePrediction[]>(FALLBACK_PREDICTIONS);
  const [drivers,     setDrivers]     = useState<Driver[]>(FALLBACK_DRIVERS);
  const [apiOnline,   setApiOnline]   = useState(false);
  const [liveCount,   setLiveCount]   = useState(100_000);

  // ── Chat state ──
  const [messages,    setMessages]    = useState<ChatMessage[]>([{ role:'ai', content:"👋 Hi, I'm MotorqAI. Ask me about vehicle health, alerts, driver performance, or breakdown predictions. I'm connected to your live fleet data." }]);
  const [chatInput,   setChatInput]   = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // ── Fetch helpers ──
  const loadStats = useCallback(async () => {
    try { setStats(await api.stats()); setApiOnline(true); } catch { /* keep fallback */ }
  }, []);

  const loadAlerts = useCallback(async () => {
    try {
      const res = await api.alerts();
      if (res.data?.length) setAlerts(res.data);
    } catch { /* keep fallback */ }
  }, []);

  const loadPredictions = useCallback(async () => {
    try {
      const res = await api.maintenance();
      if (res.data?.length) setPredictions(res.data);
    } catch { /* keep fallback */ }
  }, []);

  const loadDrivers = useCallback(async () => {
    try {
      const res = await api.drivers();
      if (res.data?.length) setDrivers(res.data);
    } catch { /* keep fallback */ }
  }, []);

  // Initial fetch
  useEffect(() => { loadStats(); loadAlerts(); }, [loadStats, loadAlerts]);

  useEffect(() => {
    if (activeTab === 'maintenance') loadPredictions();
    if (activeTab === 'drivers')     loadDrivers();
  }, [activeTab, loadPredictions, loadDrivers]);

  // Live counter
  useEffect(() => {
    const t = setInterval(() => setLiveCount(c => c + Math.floor(Math.random()*150+30)), 120);
    return () => clearInterval(t);
  }, []);

  // Auto-refresh alerts every 10s when on alerts tab
  useEffect(() => {
    if (activeTab !== 'alerts') return;
    const t = setInterval(loadAlerts, 10_000);
    return () => clearInterval(t);
  }, [activeTab, loadAlerts]);

  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior:'smooth' }); }, [messages]);

  // ── Chat ──
  async function sendChat(msg: string) {
    if (!msg.trim() || chatLoading) return;
    setMessages(prev => [...prev, { role:'user', content: msg }]);
    setChatInput('');
    setChatLoading(true);
    try {
      const res = await api.chat(msg);
      setMessages(prev => [...prev, { role:'ai', content: res.response }]);
    } catch {
      setMessages(prev => [...prev, { role:'ai', content: '⚠️ Could not reach the AI backend. Make sure the API gateway is running at http://localhost:8000 and GEMINI_API_KEY is set in .env.' }]);
    } finally {
      setChatLoading(false);
    }
  }

  async function acknowledgeAlert(alertId: string) {
    try {
      await api.acknowledgeAlert(alertId);
      setAlerts(prev => prev.filter(a => a.alert_id !== alertId));
    } catch { /* silently fail */ }
  }

  const navItems = [
    { id:'overview'     as Tab, label:'Fleet Overview',  icon:<Icon.Grid/>,   badge:0 },
    { id:null,                  label:'Fleet Map',       icon:<Icon.Map/>,    badge:0, href:'/map' },
    { id:'alerts'       as Tab, label:'Alerts',          icon:<Icon.Bell/>,   badge:stats.critical_alerts },
    { id:'maintenance'  as Tab, label:'Maintenance Risk',icon:<Icon.Wrench/>, badge:stats.vehicles_at_risk },
    { id:'drivers'      as Tab, label:'Driver Safety',   icon:<Icon.User/>,   badge:0 },
    { id:'agent'        as Tab, label:'AI Assistant',    icon:<Icon.Bot/>,    badge:0 },
    { id:'architecture' as Tab, label:'Architecture',    icon:<Icon.Cpu/>,    badge:0 },
  ];

  return (
    <div className="layout">
      {/* Topbar */}
      <header className="topbar">
        <div className="topbar-brand">
          <div className="topbar-brand-mark"><div style={{ width:14, height:14, color:'white' }}><Icon.Zap/></div></div>
          <span className="topbar-brand-name">Motorq</span>
          <span className="topbar-brand-tag">Fleet Intelligence</span>
        </div>
        <div className="topbar-right">
          {/* API status indicator */}
          <div style={{ fontSize:11, display:'flex', alignItems:'center', gap:6, color: apiOnline ? 'var(--green)' : 'var(--amber)' }}>
            <div style={{ width:6, height:6, borderRadius:'50%', background: apiOnline ? 'var(--green)' : 'var(--amber)' }} />
            {apiOnline ? 'API Connected' : 'API Fallback'}
          </div>
          <div className="live-pill" suppressHydrationWarning>
            <div className="live-dot" />
            <span suppressHydrationWarning>Live · {(liveCount/1000).toFixed(1)}K events/sec</span>
          </div>
          <div className="topbar-user">
            <div className="topbar-avatar">FA</div>
            <span>Fleet Admin</span>
            <span style={{ color:'var(--text-muted)' }}>tenant_0001</span>
          </div>
        </div>
      </header>

      {/* Sidebar */}
      <nav className="sidebar">
        <div className="nav-section-label">Navigation</div>
        {navItems.map(item =>
          item.href ? (
            <a key={item.label} href={item.href} className="nav-item">
              <div className="nav-icon">{item.icon}</div><span>{item.label}</span>
            </a>
          ) : (
            <div key={item.label} className={`nav-item ${activeTab === item.id ? 'active' : ''}`}
                 onClick={() => item.id && setActiveTab(item.id as Tab)}>
              <div className="nav-icon">{item.icon}</div>
              <span>{item.label}</span>
              {item.badge > 0 && <span className="nav-badge">{item.badge > 99 ? '99+' : item.badge}</span>}
            </div>
          )
        )}
        <div className="nav-divider" style={{ marginTop:'auto' }} />
        <div className="sidebar-footer">
          <div className="sidebar-footer-label">AI Model</div>
          <div className="sidebar-footer-value"><div style={{ width:12, height:12 }}><Icon.Bot/></div>Gemini 2.5 Pro</div>
        </div>
      </nav>

      {/* Main */}
      <main className="main-content">

        {/* ── Overview ── */}
        {activeTab === 'overview' && (
          <div>
            <div className="page-header">
              <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between' }}>
                <div><div className="page-title">Fleet Overview</div><div className="page-subtitle" suppressHydrationWarning>Real-time · {stats.total_vehicles.toLocaleString('en-US')} vehicles · Updated live</div></div>
                <button className="btn btn-ghost" style={{ fontSize:11 }} onClick={loadStats}><div style={{ width:12, height:12 }}><Icon.Refresh/></div>Refresh</button>
              </div>
            </div>
            <div className="stats-grid">
              {[
                { label:'Total Vehicles',    value: stats.total_vehicles.toLocaleString('en-US'),           sub:'8 regions',     accent:'linear-gradient(90deg,#3b82f6,#06b6d4)', spark:'#3b82f6' },
                { label:'Active Alerts',     value: stats.active_alerts.toString(),                           sub:`${stats.critical_alerts} critical`, accent:'linear-gradient(90deg,#ef4444,#f59e0b)', spark:'#ef4444' },
                { label:'At Breakdown Risk', value: stats.vehicles_at_risk.toString(),                        sub:'within 7 days', accent:'linear-gradient(90deg,#f59e0b,#ef4444)', spark:'#f59e0b' },
                { label:'Avg Driver Score',  value: `${stats.avg_driver_score}/100`,                          sub:'fleet average', accent:'linear-gradient(90deg,#22c55e,#06b6d4)', spark:'#22c55e' },
                { label:'EV Fleet',          value: `${(stats.ev_vehicles/1000).toFixed(1)}K`,               sub:`${((stats.ev_vehicles/Math.max(stats.total_vehicles,1))*100).toFixed(1)}% of fleet`, accent:'linear-gradient(90deg,#a855f7,#3b82f6)', spark:'#a855f7' },
                { label:'Events / sec',      value: `${(liveCount/1000).toFixed(0)}K+`,                      sub:'live ingestion', accent:'linear-gradient(90deg,#06b6d4,#3b82f6)', spark:'#06b6d4' },
              ].map(s => (
                <div key={s.label} className="stat-card">
                  <div className="stat-card-accent" style={{ background:s.accent }} />
                  <div className="stat-value">{s.value}</div>
                  <div className="stat-label">{s.label}</div>
                  <div className="stat-sub">{s.sub}</div>
                  <Sparkline color={s.spark} />
                </div>
              ))}
            </div>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:14 }}>
              <div className="card">
                <div className="card-header"><span className="card-title">Critical Alerts</span><button className="btn btn-ghost" style={{ fontSize:11, padding:'4px 10px' }} onClick={() => setActiveTab('alerts')}>View all →</button></div>
                <div className="table-container"><table>
                  <thead><tr><th>VIN</th><th>Type</th><th>Severity</th><th>Time</th></tr></thead>
                  <tbody>{alerts.filter(a => a.severity === 'critical' || a.severity === 'high').slice(0,4).map(a => (
                    <tr key={a.alert_id}>
                      <td className="mono">{a.vin.slice(0,12)}…</td>
                      <td style={{ fontSize:12 }}>{a.alert_type.replace(/_/g,' ')}</td>
                      <td><SeverityBadge severity={a.severity} /></td>
                      <td style={{ fontSize:11, color:'var(--text-muted)' }} suppressHydrationWarning>{formatTime(a.event_ts)}</td>
                    </tr>
                  ))}</tbody>
                </table></div>
              </div>
              <div className="card">
                <div className="card-header"><span className="card-title">Maintenance Risk</span><button className="btn btn-ghost" style={{ fontSize:11, padding:'4px 10px' }} onClick={() => setActiveTab('maintenance')}>View all →</button></div>
                <div className="table-container"><table>
                  <thead><tr><th>Vehicle</th><th>Region</th><th>Risk</th></tr></thead>
                  <tbody>{predictions.slice(0,4).map(p => (
                    <tr key={p.vin}>
                      <td><div style={{ fontWeight:600, fontSize:13 }}>{p.make} {p.model}</div><div className="mono" style={{ color:'var(--text-muted)' }}>{p.vin.slice(0,12)}…</div></td>
                      <td style={{ fontSize:12, color:'var(--text-secondary)' }}>{p.region}</td>
                      <td><RiskBar prob={p.failure_prob_7d} /></td>
                    </tr>
                  ))}</tbody>
                </table></div>
              </div>
            </div>
          </div>
        )}

        {/* ── Alerts ── */}
        {activeTab === 'alerts' && (
          <div>
            <div className="page-header">
              <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between' }}>
                <div><div className="page-title">Alert Center</div><div className="page-subtitle">Live from API · Auto-refreshes every 10 seconds</div></div>
                <button className="btn btn-ghost" style={{ fontSize:11 }} onClick={loadAlerts}><div style={{ width:12, height:12 }}><Icon.Refresh/></div>Refresh</button>
              </div>
            </div>
            <div className="card">
              <div className="card-header"><span className="card-title">{alerts.length} Active Alerts</span><div className="live-pill"><div className="live-dot" />Live</div></div>
              <div className="table-container"><table>
                <thead><tr><th>VIN</th><th>Alert Type</th><th>Severity</th><th>DTC</th><th>Time</th><th>Action</th></tr></thead>
                <tbody>{alerts.map(a => (
                  <tr key={a.alert_id}>
                    <td className="mono">{a.vin.slice(0,14)}…</td>
                    <td style={{ fontSize:12 }}>{a.alert_type.replace(/_/g,' ')}</td>
                    <td><SeverityBadge severity={a.severity} /></td>
                    <td className="mono" style={{ color:'var(--amber)' }}>{a.dtc_code || '—'}</td>
                    <td style={{ fontSize:11, color:'var(--text-muted)' }} suppressHydrationWarning>{formatTime(a.event_ts)}</td>
                    <td><button className="btn btn-ghost" style={{ fontSize:11, padding:'3px 10px' }} onClick={() => acknowledgeAlert(a.alert_id)}><div style={{ width:10, height:10 }}><Icon.Check/></div>Ack</button></td>
                  </tr>
                ))}</tbody>
              </table></div>
            </div>
          </div>
        )}

        {/* ── Maintenance ── */}
        {activeTab === 'maintenance' && (
          <div>
            <div className="page-header"><div className="page-title">Predictive Maintenance</div><div className="page-subtitle">ML-powered 7-day breakdown predictions · XGBoost · Updated nightly</div></div>
            <div className="card">
              <div className="card-header"><span className="card-title">{predictions.length} vehicles at risk (prob ≥ 50%)</span><span className="badge badge-high">XGBoost · F1=0.91</span></div>
              <div className="table-container"><table>
                <thead><tr><th>Vehicle</th><th>VIN</th><th>Region</th><th>7-Day Risk</th><th>Confidence</th><th>Action</th></tr></thead>
                <tbody>{predictions.map(p => (
                  <tr key={p.vin}>
                    <td><div style={{ fontWeight:600 }}>{p.make} {p.model}</div></td>
                    <td className="mono" style={{ color:'var(--text-muted)' }}>{p.vin.slice(0,14)}…</td>
                    <td style={{ fontSize:12 }}>{p.region}</td>
                    <td><RiskBar prob={p.failure_prob_7d} /></td>
                    <td><span className={`badge badge-${p.confidence === 'high' ? 'critical' : 'medium'}`}>{p.confidence.toUpperCase()}</span></td>
                    <td><button className="btn btn-primary" style={{ fontSize:11, padding:'4px 12px' }}>Schedule</button></td>
                  </tr>
                ))}</tbody>
              </table></div>
            </div>
          </div>
        )}

        {/* ── Drivers ── */}
        {activeTab === 'drivers' && (
          <div>
            <div className="page-header"><div className="page-title">Driver Safety Leaderboard</div><div className="page-subtitle">Weekly safety scores · Normalized per 100 km</div></div>
            <div className="card">
              <div className="card-header"><span className="card-title" suppressHydrationWarning>{drivers.length} Drivers · Weekly Period</span><span className="badge badge-low">Sorted: Worst first</span></div>
              <div className="table-container"><table>
                <thead><tr><th>Rank</th><th>Driver</th><th>Safety Score</th><th>Harsh Brakes</th><th>Overspeeding</th><th>Distance</th></tr></thead>
                <tbody>{[...drivers].sort((a,b)=>a.overall_score-b.overall_score).map((d,i) => (
                  <tr key={d.driver_id}>
                    <td style={{ fontWeight:700, color: i===0?'var(--red)':i===1?'var(--amber)':'var(--text-muted)' }}>#{i+1}</td>
                    <td><div style={{ fontWeight:600 }}>{d.full_name}</div><div className="mono" style={{ color:'var(--text-muted)' }}>{d.driver_id}</div></td>
                    <td><ScoreBar score={d.overall_score} /></td>
                    <td style={{ color: d.harsh_brake_cnt>10?'var(--red)':'inherit' }}>{d.harsh_brake_cnt}</td>
                    <td style={{ color: d.overspeeding_cnt>5?'var(--amber)':'inherit' }}>{d.overspeeding_cnt}</td>
                    <td style={{ color:'var(--text-muted)', fontSize:12 }} suppressHydrationWarning>{d.total_km.toLocaleString('en-US')} km</td>
                  </tr>
                ))}</tbody>
              </table></div>
            </div>
          </div>
        )}

        {/* ── AI Agent ── */}
        {activeTab === 'agent' && (
          <div>
            <div className="page-header"><div className="page-title">AI Fleet Assistant</div><div className="page-subtitle">Powered by LangGraph · Model: <span style={{ color:'var(--cyan)' }}>Gemini 2.5 Pro</span> · Connected to live fleet data</div></div>
            <div className="card" style={{ padding:0 }}>
              <div className="chat-container">
                <div className="chat-messages">
                  {messages.map((m,i) => (
                    <div key={i} className={`chat-message ${m.role==='user'?'user-msg':''}`}>
                      <div className={`chat-avatar ${m.role==='user'?'usr-av':'ai-av'}`}>
                        {m.role==='user'?'FA':<div style={{ width:14, height:14, color:'white' }}><Icon.Bot/></div>}
                      </div>
                      <div className={`chat-bubble ${m.role==='user'?'usr-bubble':''}`}>{m.content}</div>
                    </div>
                  ))}
                  {chatLoading && (
                    <div className="chat-message">
                      <div className="chat-avatar ai-av"><div style={{ width:14, height:14, color:'white' }}><Icon.Bot/></div></div>
                      <div className="chat-bubble">
                        <div style={{ display:'flex', gap:6, alignItems:'center' }}>
                          <div className="spinner" style={{ width:14, height:14 }} />
                          <span style={{ color:'var(--text-muted)', fontSize:12 }}>Querying Gemini…</span>
                        </div>
                      </div>
                    </div>
                  )}
                  <div ref={messagesEndRef} />
                </div>
                <div className="chat-suggestions">
                  {SUGGESTIONS.map(s => <button key={s} className="chat-suggestion" onClick={() => sendChat(s)}>{s}</button>)}
                </div>
                <div className="chat-input-row">
                  <input className="chat-input" placeholder="Ask about your fleet…" value={chatInput}
                    onChange={e => setChatInput(e.target.value)}
                    onKeyDown={e => e.key==='Enter' && sendChat(chatInput)} />
                  <button className="btn btn-primary" onClick={() => sendChat(chatInput)}>
                    <div style={{ width:13, height:13 }}><Icon.Send/></div>Send
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ── Architecture ── */}
        {activeTab === 'architecture' && <ArchitectureTab />}

      </main>
    </div>
  );
}
