"""
Driver Safety Scoring Engine

Computes multi-dimensional safety scores per driver per period.
Implements:
  - Weighted safety score (harsh events, speeding, night driving, idle)
  - Rolling window computation (daily / weekly / monthly)
  - Top-K leaderboard using Count-Min Sketch for streaming
  - Trip segmentation via Dynamic Programming
  - Anomaly detection for outlier driver behavior
"""

import json
import math
import os
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple
import random

import numpy as np

# ── Safety Score Weights ─────────────────────────────────────────────

SCORE_WEIGHTS = {
    "harsh_brake": -5.0,       # per event
    "harsh_accel": -3.0,       # per event
    "sharp_turn": -3.0,        # per event
    "overspeeding": -4.0,      # per event
    "night_driving_h": -1.5,   # per hour
    "idle_long_events": -2.0,  # per event
    "rapid_lane_change": -2.0, # per event
}

MAX_SCORE = 100.0
BASE_SCORE = 100.0
MIN_SCORE = 0.0

# ── Safety Score Computation ─────────────────────────────────────────

@dataclass
class DriverPeriodStats:
    driver_id: str
    vin: str
    tenant_id: str
    period: str            # daily / weekly / monthly
    period_start: date
    harsh_brake_cnt: int = 0
    harsh_accel_cnt: int = 0
    sharp_turn_cnt: int = 0
    overspeeding_cnt: int = 0
    rapid_lane_change_cnt: int = 0
    idle_long_events: int = 0
    night_driving_h: float = 0.0
    total_km: float = 0.0
    total_trips: int = 0
    overall_score: float = 100.0

    def compute_score(self) -> float:
        """
        Safety score formula (100 = perfect, 0 = worst).
        Penalties are normalized per 100 km driven to be fair.
        """
        km_factor = max(self.total_km / 100.0, 1.0)  # normalize per 100 km

        deductions = (
            (self.harsh_brake_cnt / km_factor) * abs(SCORE_WEIGHTS["harsh_brake"]) +
            (self.harsh_accel_cnt / km_factor) * abs(SCORE_WEIGHTS["harsh_accel"]) +
            (self.sharp_turn_cnt / km_factor) * abs(SCORE_WEIGHTS["sharp_turn"]) +
            (self.overspeeding_cnt / km_factor) * abs(SCORE_WEIGHTS["overspeeding"]) +
            self.night_driving_h * abs(SCORE_WEIGHTS["night_driving_h"]) +
            (self.idle_long_events / km_factor) * abs(SCORE_WEIGHTS["idle_long_events"]) +
            (self.rapid_lane_change_cnt / km_factor) * abs(SCORE_WEIGHTS["rapid_lane_change"])
        )

        score = max(MIN_SCORE, min(MAX_SCORE, BASE_SCORE - deductions))
        self.overall_score = round(float(score), 2)
        return self.overall_score

    def to_dict(self) -> dict:
        d = asdict(self)
        d["period_start"] = self.period_start.isoformat()
        return d


def compute_daily_score(
    driver_id: str,
    vin: str,
    tenant_id: str,
    events: List[dict],
    target_date: date,
) -> DriverPeriodStats:
    """Compute a driver's safety score for a single day."""
    stats = DriverPeriodStats(
        driver_id=driver_id,
        vin=vin,
        tenant_id=tenant_id,
        period="daily",
        period_start=target_date,
    )

    for event in events:
        evt_type = event.get("evt")
        if evt_type == "HARSH_BRAKE":
            stats.harsh_brake_cnt += 1
        elif evt_type == "HARSH_ACCEL":
            stats.harsh_accel_cnt += 1
        elif evt_type == "SHARP_TURN":
            stats.sharp_turn_cnt += 1
        elif evt_type == "OVERSPEEDING":
            stats.overspeeding_cnt += 1
        elif evt_type == "RAPID_LANE_CHANGE":
            stats.rapid_lane_change_cnt += 1
        elif evt_type == "IDLE_LONG":
            stats.idle_long_events += 1

        # Night driving (22:00 – 06:00)
        ts = event.get("ts", "")
        if ts:
            try:
                hour = int(ts[11:13])  # HH from ISO string
                if hour >= 22 or hour < 6:
                    stats.night_driving_h += 1 / 60.0  # 1 event ≈ 1 minute
            except (ValueError, IndexError):
                pass

    stats.total_km = sum(
        event.get("speed_kmh", 0) / 3600 for event in events
    )  # rough: speed × 1s = km
    stats.compute_score()
    return stats


# ── Trip Segmentation (Dynamic Programming) ──────────────────────────

@dataclass
class TripSegment:
    start_idx: int
    end_idx: int
    start_time: str
    end_time: str
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    distance_km: float
    max_speed_kmh: float
    harsh_events: int


def segment_trips(events: List[dict], min_stop_minutes: int = 5) -> List[TripSegment]:
    """
    DP-based trip segmentation:
    - Moving state: speed > 2 km/h
    - Stop detected: speed < 2 km/h for > min_stop_minutes consecutive events
    - Each moving segment between stops = one trip

    Complexity: O(n) where n = number of events
    """
    if not events:
        return []

    trips: List[TripSegment] = []
    n = len(events)
    in_trip = False
    trip_start = 0
    stop_count = 0
    STOP_THRESHOLD = min_stop_minutes  # events (1 per minute assumed)

    for i in range(n):
        speed = events[i].get("speed_kmh", 0) or 0
        is_moving = speed > 2.0

        if is_moving:
            if not in_trip:
                in_trip = True
                trip_start = i
            stop_count = 0
        else:
            if in_trip:
                stop_count += 1
                if stop_count >= STOP_THRESHOLD:
                    # Trip ended
                    trip_end = i - STOP_THRESHOLD
                    if trip_end > trip_start:
                        segment = _build_segment(events, trip_start, trip_end)
                        if segment:
                            trips.append(segment)
                    in_trip = False
                    stop_count = 0

    # Close any open trip at end
    if in_trip and n - 1 > trip_start:
        segment = _build_segment(events, trip_start, n - 1)
        if segment:
            trips.append(segment)

    return trips


def _build_segment(events: List[dict], start: int, end: int) -> Optional[TripSegment]:
    """Build a TripSegment from a slice of events."""
    seg_events = events[start:end + 1]
    if not seg_events:
        return None

    speeds = [e.get("speed_kmh", 0) or 0 for e in seg_events]
    harsh = sum(1 for e in seg_events if e.get("evt") is not None)

    # Haversine distance approximation
    total_dist = sum(s / 3600 for s in speeds)  # 1 event ≈ 1s

    start_e = seg_events[0]
    end_e = seg_events[-1]

    return TripSegment(
        start_idx=start,
        end_idx=end,
        start_time=start_e.get("ts", ""),
        end_time=end_e.get("ts", ""),
        start_lat=start_e.get("lat", 0),
        start_lon=start_e.get("lon", 0),
        end_lat=end_e.get("lat", 0),
        end_lon=end_e.get("lon", 0),
        distance_km=round(total_dist, 2),
        max_speed_kmh=round(max(speeds), 1),
        harsh_events=harsh,
    )


# ── Count-Min Sketch — Top-K Dangerous Drivers ───────────────────────

class CountMinSketch:
    """
    Approximate frequency counter using Count-Min Sketch.
    Space: O(w × d), Time per update/query: O(d)
    Used for Top-K driver leaderboard in streaming context.
    """

    def __init__(self, width: int = 1000, depth: int = 5):
        self.width = width
        self.depth = depth
        self.table = [[0] * width for _ in range(depth)]
        # Fixed hash seeds
        self.seeds = [random.randint(1, 10**9) for _ in range(depth)]

    def _hash(self, key: str, row: int) -> int:
        h = hash(key + str(self.seeds[row]))
        return abs(h) % self.width

    def update(self, key: str, count: int = 1) -> None:
        """Increment the estimated count for key."""
        for i in range(self.depth):
            col = self._hash(key, i)
            self.table[i][col] += count

    def query(self, key: str) -> int:
        """Estimate the frequency of key (always an overestimate)."""
        return min(self.table[i][self._hash(key, i)] for i in range(self.depth))


class DriverLeaderboard:
    """
    Maintains a Top-K dangerous driver leaderboard using Count-Min Sketch
    for space-efficient frequency estimation.
    """

    def __init__(self, k: int = 100):
        self.k = k
        self.sketch = CountMinSketch()
        self._exact: Dict[str, int] = {}  # exact for known top-K candidates

    def record_event(self, driver_id: str, penalty_points: int = 1) -> None:
        """Record a penalty event for a driver."""
        self.sketch.update(driver_id, penalty_points)
        # Also track exactly for recent candidates
        self._exact[driver_id] = self._exact.get(driver_id, 0) + penalty_points
        # Trim exact tracking to 2K candidates
        if len(self._exact) > self.k * 2:
            sorted_items = sorted(self._exact.items(), key=lambda x: -x[1])
            self._exact = dict(sorted_items[:self.k])

    def top_k(self) -> List[Tuple[str, int]]:
        """Return top-K drivers by penalty points."""
        return sorted(self._exact.items(), key=lambda x: -x[1])[:self.k]

    def estimate(self, driver_id: str) -> int:
        """Estimate penalty points for a driver."""
        return self._exact.get(driver_id) or self.sketch.query(driver_id)


# ── Anomaly Detection ─────────────────────────────────────────────────

def detect_anomalous_drivers(
    scores: List[Dict],
    z_threshold: float = 2.5,
) -> List[Dict]:
    """
    Flag drivers whose behavior is statistically anomalous.
    Uses Z-score: (score - mean) / std > threshold = anomaly.
    """
    if len(scores) < 10:
        return []

    score_values = [s["overall_score"] for s in scores]
    mean = np.mean(score_values)
    std = np.std(score_values)

    if std < 0.001:
        return []

    anomalies = []
    for s in scores:
        z = (s["overall_score"] - mean) / std
        if z < -z_threshold:  # significantly below average
            anomalies.append({
                **s,
                "z_score": round(float(z), 3),
                "anomaly_reason": f"Score {s['overall_score']:.1f} is {abs(z):.1f}σ below fleet average ({mean:.1f})",
            })

    return sorted(anomalies, key=lambda x: x["z_score"])


# ── Demo / test ────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Driver Safety Score Demo ===\n")

    # Simulate some events for a driver
    sample_events = [
        {"ts": "2026-09-25T10:15:00Z", "speed_kmh": 65, "evt": "HARSH_BRAKE"},
        {"ts": "2026-09-25T10:16:00Z", "speed_kmh": 45, "evt": None},
        {"ts": "2026-09-25T22:05:00Z", "speed_kmh": 80, "evt": "OVERSPEEDING"},
        {"ts": "2026-09-25T22:07:00Z", "speed_kmh": 70, "evt": "SHARP_TURN"},
        {"ts": "2026-09-25T22:10:00Z", "speed_kmh": 0, "evt": None},
    ] * 20

    stats = compute_daily_score("DRV-12345", "1HGCM82633A004352", "tenant_0001",
                                 sample_events, date(2026, 9, 25))
    print(f"Driver score: {stats.overall_score}")
    print(f"Stats: {json.dumps(stats.to_dict(), indent=2)}")

    # Trip segmentation
    trip_events = [
        {"ts": f"2026-09-25T{h:02d}:{m:02d}:00Z", "speed_kmh": 60 if 8 <= h < 12 else 0, "evt": None,
         "lat": 19.07 + h * 0.001, "lon": 72.87}
        for h in range(24) for m in range(60)
    ]
    trips = segment_trips(trip_events)
    print(f"\nTrip segments detected: {len(trips)}")
    for t in trips[:3]:
        print(f"  Trip: {t.start_time[:16]} → {t.end_time[:16]}, {t.distance_km:.1f} km")

    # Count-Min Sketch leaderboard
    leaderboard = DriverLeaderboard(k=10)
    for _ in range(1000):
        drv = f"DRV-{random.randint(1000, 1050)}"
        leaderboard.record_event(drv, random.randint(1, 5))

    print(f"\nTop 5 dangerous drivers:")
    for drv, pts in leaderboard.top_k()[:5]:
        print(f"  {drv}: {pts} penalty points (est: {leaderboard.estimate(drv)})")
