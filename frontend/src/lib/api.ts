/**
 * Motorq API Client
 * Connects the frontend to the FastAPI backend at localhost:8000
 */

const BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  });
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

// ── Types ─────────────────────────────────────────────────────────────────

export interface FleetStats {
  total_vehicles: number;
  active_alerts: number;
  critical_alerts: number;
  vehicles_at_risk: number;
  avg_driver_score: number;
  ev_vehicles: number;
}

export interface Vehicle {
  vin: string; make: string; model: string; fuel_type: string;
  year: number; region: string; odometer_km: number;
  is_active: boolean; speed_kmh?: number; lat?: number; lon?: number;
}

export interface Alert {
  alert_id: string; vin: string; alert_type: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  title?: string; event_ts: string; lat?: number; lon?: number; dtc_code?: string;
}

export interface MaintenancePrediction {
  vin: string; make: string; model: string; region: string;
  failure_prob_7d: number; recommended_action: string;
  confidence: 'high' | 'medium' | 'low';
}

export interface Driver {
  driver_id: string; full_name: string; overall_score: number;
  harsh_brake_cnt: number; overspeeding_cnt: number; total_km: number;
}

export interface PaginatedResponse<T> {
  data: T[]; total: number; page: number; page_size: number;
}

// ── API calls ──────────────────────────────────────────────────────────────

export const api = {
  health: () => apiFetch<Record<string, string>>('/health'),

  stats: () => apiFetch<FleetStats>('/api/stats'),

  fleet: (page = 1, pageSize = 50) =>
    apiFetch<PaginatedResponse<Vehicle>>(`/api/fleet?page=${page}&page_size=${pageSize}`),

  alerts: (severity?: string, page = 1) =>
    apiFetch<PaginatedResponse<Alert>>(
      `/api/alerts?page=${page}&page_size=50${severity ? `&severity=${severity}` : ''}`
    ),

  acknowledgeAlert: (alertId: string) =>
    apiFetch<{ alert_id: string; status: string }>(`/api/alerts/${alertId}`, {
      method: 'PATCH',
      body: JSON.stringify({ status: 'acknowledged' }),
    }),

  maintenance: (minProb = 0.5, page = 1) =>
    apiFetch<PaginatedResponse<MaintenancePrediction>>(
      `/api/maintenance/predictions?min_prob=${minProb}&page=${page}`
    ),

  drivers: (period = 'weekly', page = 1) =>
    apiFetch<PaginatedResponse<Driver>>(`/api/drivers?period=${period}&page=${page}`),

  chat: (message: string) =>
    apiFetch<{ response: string; sources?: string[] }>('/api/agent/chat', {
      method: 'POST',
      body: JSON.stringify({ message }),
    }),

  me: () => apiFetch<{ sub: string; tenant_id: string; role: string }>('/api/me'),
};

// ── Mock fallbacks (used when backend returns no data) ────────────────────

export const FALLBACK_STATS: FleetStats = {
  total_vehicles: 100_000, active_alerts: 342, critical_alerts: 18,
  vehicles_at_risk: 156, avg_driver_score: 72.4, ev_vehicles: 28_400,
};

export const FALLBACK_ALERTS: Alert[] = [
  { alert_id:'1', vin:'1HGCM82633A004352', alert_type:'CRITICAL_DTC',     severity:'critical', event_ts: new Date().toISOString(),              dtc_code:'P0300' },
  { alert_id:'2', vin:'1FTFW1E55NFA12345', alert_type:'LOW_BATTERY',      severity:'high',     event_ts: new Date(Date.now()-120000).toISOString() },
  { alert_id:'3', vin:'WVW1234567890ABCD', alert_type:'HARSH_BRAKE',      severity:'medium',   event_ts: new Date(Date.now()-300000).toISOString() },
  { alert_id:'4', vin:'JHM1234567890ABCD', alert_type:'BATTERY_OVERHEAT', severity:'critical', event_ts: new Date(Date.now()-60000).toISOString()  },
  { alert_id:'5', vin:'YV1KS9143P1234567', alert_type:'GEO_FENCE_BREACH', severity:'medium',   event_ts: new Date(Date.now()-900000).toISOString() },
];

export const FALLBACK_PREDICTIONS: MaintenancePrediction[] = [
  { vin:'1HGCM82633A004352', make:'Ford',    model:'F-150',   region:'Mumbai',    failure_prob_7d:0.91, recommended_action:'URGENT: Remove from service immediately.',   confidence:'high'   },
  { vin:'1FTFW1E55NFA12345', make:'Hyundai', model:'IONIQ 6', region:'Delhi',     failure_prob_7d:0.78, recommended_action:'Schedule diagnostic scan within 24 hours.', confidence:'high'   },
  { vin:'WVW1234567890ABCD', make:'Toyota',  model:'Camry',   region:'Bangalore', failure_prob_7d:0.65, recommended_action:'Preventive check within 3 days.',           confidence:'medium' },
  { vin:'JHM1234567890ABCD', make:'Honda',   model:'Accord',  region:'Chennai',   failure_prob_7d:0.58, recommended_action:'Monitor closely. Service within 7 days.',   confidence:'medium' },
];

export const FALLBACK_DRIVERS: Driver[] = [
  { driver_id:'DRV-48291', full_name:'Rahul Sharma', overall_score:42.1, harsh_brake_cnt:23, overspeeding_cnt:8, total_km:1240 },
  { driver_id:'DRV-38821', full_name:'Priya Nair',   overall_score:55.8, harsh_brake_cnt:14, overspeeding_cnt:3, total_km:890  },
  { driver_id:'DRV-52210', full_name:'Amit Kumar',   overall_score:61.2, harsh_brake_cnt:11, overspeeding_cnt:5, total_km:1560 },
  { driver_id:'DRV-10482', full_name:'Sneha Patel',  overall_score:88.4, harsh_brake_cnt:2,  overspeeding_cnt:0, total_km:720  },
  { driver_id:'DRV-77391', full_name:'Vikram Singh', overall_score:91.7, harsh_brake_cnt:1,  overspeeding_cnt:0, total_km:980  },
];
