"""
Unit tests for core modules.
Run: pytest tests/unit/ -v --cov=services --cov-report=html
"""

import json
import sys
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

# ── Add service paths ─────────────────────────────────────────────────
sys.path.insert(0, "services/simulator")
sys.path.insert(0, "services/ml-engine")
sys.path.insert(0, "services/ingestion")


# ────────────────────────────────────────────────────────────────────
#  VIN Generator Tests
# ────────────────────────────────────────────────────────────────────

class TestVINGenerator:
    def setup_method(self):
        from vin_generator import generate_vin, validate_vin, generate_vin_batch
        self.generate_vin = generate_vin
        self.validate_vin = validate_vin
        self.generate_vin_batch = generate_vin_batch

    def test_vin_length(self):
        vin = self.generate_vin()
        assert len(vin) == 17

    def test_vin_no_ioq(self):
        for _ in range(100):
            vin = self.generate_vin()
            assert "I" not in vin
            assert "O" not in vin
            assert "Q" not in vin

    def test_vin_valid_characters(self):
        allowed = set("ABCDEFGHJKLMNPRSTUVWXYZ0123456789")
        for _ in range(100):
            vin = self.generate_vin()
            assert all(c in allowed for c in vin), f"Invalid char in {vin}"

    def test_vin_check_digit(self):
        for _ in range(100):
            vin = self.generate_vin()
            assert self.validate_vin(vin), f"VIN {vin} failed check digit validation"

    def test_validate_vin_invalid_length(self):
        assert not self.validate_vin("SHORT")

    def test_validate_vin_with_ioq(self):
        assert not self.validate_vin("1HGCM82633I004352")  # contains I

    def test_validate_vin_wrong_check_digit(self):
        vin = list(self.generate_vin())
        # Corrupt the check digit
        vin[8] = "0" if vin[8] != "0" else "1"
        assert not self.validate_vin("".join(vin))

    def test_batch_generation_unique(self):
        batch = self.generate_vin_batch(1000)
        assert len(set(batch)) == 1000  # all unique

    def test_batch_all_valid(self):
        batch = self.generate_vin_batch(100)
        for vin in batch:
            assert self.validate_vin(vin), f"{vin} invalid"


# ────────────────────────────────────────────────────────────────────
#  Driver Safety Score Tests
# ────────────────────────────────────────────────────────────────────

class TestDriverSafetyScore:
    def setup_method(self):
        from driver_score import (
            compute_daily_score, DriverPeriodStats,
            segment_trips, CountMinSketch, DriverLeaderboard,
            detect_anomalous_drivers
        )
        self.compute_daily_score = compute_daily_score
        self.DriverPeriodStats = DriverPeriodStats
        self.segment_trips = segment_trips
        self.CountMinSketch = CountMinSketch
        self.DriverLeaderboard = DriverLeaderboard
        self.detect_anomalous_drivers = detect_anomalous_drivers

    def _make_events(self, harsh_events=None, hours=None):
        events = []
        harsh_events = harsh_events or []
        hours = hours or [10]
        for h in hours:
            for m in range(60):
                evt = None
                if harsh_events and (h * 60 + m) < len(harsh_events):
                    evt = harsh_events[h * 60 + m]
                events.append({
                    "ts": f"2026-09-25T{h:02d}:{m:02d}:00Z",
                    "speed_kmh": 60.0,
                    "evt": evt,
                    "lat": 19.07,
                    "lon": 72.87,
                })
        return events

    def test_perfect_score(self):
        """Driver with no harsh events should get score near 100."""
        events = self._make_events()
        stats = self.compute_daily_score("DRV-001", "VIN1", "tenant_001", events, date(2026, 9, 25))
        assert stats.overall_score >= 95.0

    def test_harsh_brake_reduces_score(self):
        """Harsh braking events should reduce score."""
        events = [{"ts": f"2026-09-25T10:{m:02d}:00Z", "speed_kmh": 70, "evt": "HARSH_BRAKE"}
                  for m in range(30)]
        no_harsh_events = [{"ts": f"2026-09-25T10:{m:02d}:00Z", "speed_kmh": 70, "evt": None}
                           for m in range(30)]

        stats_harsh = self.compute_daily_score("DRV-001", "VIN1", "tenant_001", events, date(2026, 9, 25))
        stats_clean = self.compute_daily_score("DRV-002", "VIN2", "tenant_001", no_harsh_events, date(2026, 9, 25))
        assert stats_harsh.overall_score < stats_clean.overall_score

    def test_score_within_bounds(self):
        """Score must always be between 0 and 100."""
        # Extreme case: lots of harsh events
        events = [{"ts": f"2026-09-25T{h:02d}:{m:02d}:00Z", "speed_kmh": 90, "evt": "HARSH_BRAKE"}
                  for h in range(8) for m in range(60)]
        stats = self.compute_daily_score("DRV-999", "VIN1", "tenant_001", events, date(2026, 9, 25))
        assert 0 <= stats.overall_score <= 100

    def test_trip_segmentation_empty(self):
        """Empty event list should return no trips."""
        trips = self.segment_trips([])
        assert trips == []

    def test_trip_segmentation_single_trip(self):
        """Continuous driving should produce one trip."""
        events = [
            {"ts": f"2026-09-25T10:{m:02d}:00Z", "speed_kmh": 60, "evt": None, "lat": 19.07, "lon": 72.87}
            for m in range(30)
        ] + [
            {"ts": f"2026-09-25T10:{30+m:02d}:00Z", "speed_kmh": 0, "evt": None, "lat": 19.07, "lon": 72.87}
            for m in range(10)
        ]
        trips = self.segment_trips(events, min_stop_minutes=5)
        assert len(trips) >= 1

    def test_count_min_sketch_update_query(self):
        """CMS should return an estimate >= actual count."""
        cms = self.CountMinSketch(width=100, depth=5)
        cms.update("driver_A", 10)
        cms.update("driver_B", 5)
        assert cms.query("driver_A") >= 10
        assert cms.query("driver_B") >= 5
        assert cms.query("driver_C") >= 0  # never seen

    def test_leaderboard_top_k(self):
        """Leaderboard should return correct top-K drivers."""
        lb = self.DriverLeaderboard(k=5)
        lb.record_event("DRV-BAD", 100)
        lb.record_event("DRV-OK", 10)
        lb.record_event("DRV-GOOD", 2)
        top = lb.top_k()
        assert top[0][0] == "DRV-BAD"
        assert top[0][1] == 100

    def test_anomaly_detection(self):
        """Outlier drivers should be flagged as anomalous."""
        scores = [{"driver_id": f"DRV-{i}", "overall_score": 75.0} for i in range(20)]
        scores.append({"driver_id": "DRV-BAD", "overall_score": 20.0})  # outlier
        anomalies = self.detect_anomalous_drivers(scores, z_threshold=1.5)
        assert any(a["driver_id"] == "DRV-BAD" for a in anomalies)


# ────────────────────────────────────────────────────────────────────
#  Chaos Module Tests
# ────────────────────────────────────────────────────────────────────

class TestChaosModule:
    def setup_method(self):
        from chaos import BurstSimulator, OutOfOrderInjector, DuplicateInjector, ChaosEngine
        self.BurstSimulator = BurstSimulator
        self.OutOfOrderInjector = OutOfOrderInjector
        self.DuplicateInjector = DuplicateInjector
        self.ChaosEngine = ChaosEngine

    def test_burst_simulator_normal_rate(self):
        bs = self.BurstSimulator(base_rate=100_000)
        assert bs.current_rate() == 100_000

    def test_burst_simulator_burst_rate(self):
        bs = self.BurstSimulator(base_rate=100_000, burst_multiplier=3)
        bs.trigger_burst()
        assert bs.current_rate() == 300_000

    def test_duplicate_injector_rate(self):
        """Should produce duplicates at approximately the configured rate."""
        injector = self.DuplicateInjector(duplicate_rate=0.5)
        total_output = sum(len(injector.inject("event")) for _ in range(1000))
        # With 50% dup rate, expected output is ~1500
        assert 1200 <= total_output <= 1800

    def test_chaos_engine_no_data_loss(self):
        """All events should eventually be emitted (no drops)."""
        engine = self.ChaosEngine(ooo_fraction=0.0, duplicate_rate=0.0)
        sample = '{"vin":"TEST","seq":1}'
        results = engine.process(sample)
        assert len(results) >= 1  # no drops

    def test_chaos_engine_stats(self):
        engine = self.ChaosEngine()
        for _ in range(100):
            engine.process('{"test": 1}')
        stats = engine.stats()
        assert stats["emitted"] >= 100


# ────────────────────────────────────────────────────────────────────
#  Ingestion Schema Validation Tests (Pydantic)
# ────────────────────────────────────────────────────────────────────

class TestIngestionValidation:
    def setup_method(self):
        from main import TelemetryEventIn
        self.Model = TelemetryEventIn
        self.valid_payload = {
            "vin": "1HGCM82633A004352",
            "ts": "2026-09-25T10:15:02.120Z",
            "lat": 21.17,
            "lon": 72.83,
            "speed_kmh": 64.2,
            "soc_pct": 41.0,
            "odo_km": 18234.7,
            "dtc": ["P0301"],
            "evt": "HARSH_BRAKE",
            "seq": 88412,
            "fuel_pct": None,
            "heading": 180.0,
            "altitude_m": 15.0,
            "engine_rpm": 2100,
            "battery_temp_c": None,
            "tenant_id": "tenant_0001",
            "event_id": "550e8400-e29b-41d4-a716-446655440000",
        }

    def test_valid_event_accepted(self):
        from pydantic import ValidationError
        try:
            obj = self.Model(**self.valid_payload)
            assert obj.vin == "1HGCM82633A004352"
        except Exception as e:
            pytest.fail(f"Valid event rejected: {e}")

    def test_vin_with_i_rejected(self):
        from pydantic import ValidationError
        bad = {**self.valid_payload, "vin": "1HGIM82633A004352"}
        with pytest.raises((ValidationError, ValueError)):
            self.Model(**bad)

    def test_vin_with_o_rejected(self):
        from pydantic import ValidationError
        bad = {**self.valid_payload, "vin": "1HGOM82633A004352"}
        with pytest.raises((ValidationError, ValueError)):
            self.Model(**bad)

    def test_invalid_dtc_format_rejected(self):
        from pydantic import ValidationError
        bad = {**self.valid_payload, "dtc": ["INVALID_DTC"]}
        with pytest.raises((ValidationError, ValueError)):
            self.Model(**bad)

    def test_speed_out_of_range(self):
        from pydantic import ValidationError
        bad = {**self.valid_payload, "speed_kmh": 999}
        with pytest.raises((ValidationError, ValueError)):
            self.Model(**bad)

    def test_soc_out_of_range(self):
        from pydantic import ValidationError
        bad = {**self.valid_payload, "soc_pct": 110}
        with pytest.raises((ValidationError, ValueError)):
            self.Model(**bad)

    def test_lat_out_of_range(self):
        from pydantic import ValidationError
        bad = {**self.valid_payload, "lat": 95.0}
        with pytest.raises((ValidationError, ValueError)):
            self.Model(**bad)
