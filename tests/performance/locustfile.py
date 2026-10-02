"""
Load test using Locust at 100K events/second.
Tests the ingestion service under peak load.

Run:
  locust -f locustfile.py --headless -u 1000 -r 100 --run-time 5m --host http://localhost:8001
"""

import json
import random
import uuid
from datetime import datetime, timezone

from locust import HttpUser, between, events, task
from locust.runners import MasterRunner


VINS = [f"1HGC{i:013d}" for i in range(10000)]  # pre-generated VINs
TENANTS = [f"tenant_{i:04d}" for i in range(1, 51)]


def generate_event():
    return {
        "vin": random.choice(VINS),
        "ts": datetime.now(timezone.utc).isoformat(),
        "lat": round(random.uniform(12.0, 28.0), 6),
        "lon": round(random.uniform(72.0, 88.0), 6),
        "speed_kmh": round(random.uniform(0, 120), 1),
        "soc_pct": round(random.uniform(10, 100), 1) if random.random() > 0.5 else None,
        "odo_km": round(random.uniform(1000, 200000), 1),
        "dtc": ["P0301"] if random.random() < 0.02 else [],
        "evt": random.choice(["HARSH_BRAKE", None, None, None, None]),
        "seq": random.randint(1, 1_000_000),
        "fuel_pct": round(random.uniform(5, 100), 1) if random.random() > 0.5 else None,
        "heading": round(random.uniform(0, 360), 1),
        "altitude_m": round(random.uniform(5, 900), 1),
        "engine_rpm": random.randint(700, 4000) if random.random() > 0.5 else None,
        "battery_temp_c": round(random.uniform(20, 40), 1) if random.random() > 0.5 else None,
        "tenant_id": random.choice(TENANTS),
        "event_id": str(uuid.uuid4()),
    }


class TelemetryIngestionUser(HttpUser):
    """
    Simulates vehicle telemetry ingestion at high throughput.
    Each user sends ~10 requests/second.
    At 1000 users: ~10,000 requests/sec (each batch = 10 events → 100K events/sec).
    """
    wait_time = between(0.05, 0.15)  # 7-20 requests/sec per user

    @task(8)
    def ingest_batch(self):
        """Send a batch of 10 events (most common operation)."""
        batch = {"events": [generate_event() for _ in range(10)]}
        with self.client.post(
            "/ingest/batch",
            json=batch,
            catch_response=True,
            name="/ingest/batch",
        ) as response:
            if response.status_code == 202:
                response.success()
            elif response.status_code == 429:
                response.success()  # rate limiting is expected behavior
            else:
                response.failure(f"Unexpected: {response.status_code}")

    @task(2)
    def ingest_single(self):
        """Send a single event."""
        event = generate_event()
        with self.client.post(
            "/ingest",
            json=event,
            catch_response=True,
            name="/ingest",
        ) as response:
            if response.status_code in (202, 200):
                response.success()
            elif response.status_code == 429:
                response.success()
            else:
                response.failure(f"Status {response.status_code}")

    @task(1)
    def health_check(self):
        """Periodic health check."""
        self.client.get("/health", name="/health")


class APIGatewayUser(HttpUser):
    """Simulates fleet dashboard API usage."""
    wait_time = between(0.5, 2.0)
    host = "http://localhost:8000"

    @task(5)
    def get_fleet(self):
        self.client.get("/api/fleet?page=1&page_size=50", name="/api/fleet")

    @task(3)
    def get_alerts(self):
        self.client.get("/api/alerts?status=open&page=1", name="/api/alerts")

    @task(2)
    def get_maintenance(self):
        self.client.get("/api/maintenance/predictions?min_prob=0.5", name="/api/maintenance")

    @task(1)
    def get_drivers(self):
        self.client.get("/api/drivers?period=weekly", name="/api/drivers")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("=" * 60)
    print("Motorq Load Test Starting")
    print(f"Target: {environment.host}")
    print("=" * 60)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    stats = environment.stats.total
    print("\n" + "=" * 60)
    print("Load Test Complete")
    print(f"  Total requests:    {stats.num_requests:,}")
    print(f"  Failed requests:   {stats.num_failures:,}")
    print(f"  Avg response:      {stats.avg_response_time:.1f} ms")
    print(f"  p95 response:      {stats.get_response_time_percentile(0.95):.1f} ms")
    print(f"  p99 response:      {stats.get_response_time_percentile(0.99):.1f} ms")
    print(f"  Throughput:        {stats.total_rps:.1f} req/sec")
    print("=" * 60)
