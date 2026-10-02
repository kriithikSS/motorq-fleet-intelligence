"""
Real-time Telemetry Event Emitter — the core of the data simulator.

Emits 1 event/second per vehicle across 100K vehicles using asyncio.
Produces realistic telemetry: location, speed, SoC, DTCs, harsh events.
Publishes to Kafka topic: raw-telemetry
"""

import asyncio
import json
import math
import os
import random
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

# ── Telemetry Event Schema ──────────────────────────────────────────

HARSH_EVENTS = [
    "HARSH_BRAKE", "HARSH_ACCEL", "SHARP_TURN",
    "RAPID_LANE_CHANGE", "OVERSPEEDING", "IDLE_LONG",
]

OBD_DTCS_POOL = [
    "P0100", "P0101", "P0171", "P0174", "P0300", "P0301", "P0302",
    "P0420", "P0442", "P0500", "P0700", "C0035", "U0001", "U0100",
]


@dataclass
class TelemetryEvent:
    vin: str
    ts: str              # ISO8601 UTC timestamp
    lat: float
    lon: float
    speed_kmh: float
    soc_pct: Optional[float]   # None for ICE vehicles
    odo_km: float
    dtc: List[str]
    evt: Optional[str]         # harsh event type, None if normal
    seq: int                   # monotonic sequence per VIN
    fuel_pct: Optional[float]  # None for EV vehicles
    heading: float             # 0-360 degrees
    altitude_m: float
    engine_rpm: Optional[int]
    battery_temp_c: Optional[float]
    tenant_id: str
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_json(self) -> str:
        d = asdict(self)
        return json.dumps(d, separators=(",", ":"))


# ── Vehicle State (in-memory for simulation) ───────────────────────

class VehicleState:
    def __init__(self, vin: str, home_lat: float, home_lon: float,
                 fuel_type: str, tenant_id: str, odometer: float):
        self.vin = vin
        self.lat = home_lat + random.uniform(-0.01, 0.01)
        self.lon = home_lon + random.uniform(-0.01, 0.01)
        self.heading = random.uniform(0, 360)
        self.speed_kmh = 0.0
        self.soc_pct = random.uniform(20, 100) if fuel_type == "EV" else None
        self.fuel_pct = random.uniform(20, 100) if fuel_type != "EV" else None
        self.odo_km = odometer
        self.engine_rpm = None if fuel_type == "EV" else random.randint(700, 2500)
        self.battery_temp_c = random.uniform(20, 35) if fuel_type == "EV" else None
        self.fuel_type = fuel_type
        self.tenant_id = tenant_id
        self.seq = random.randint(1000, 100000)
        self.altitude_m = random.uniform(5, 900)
        self._is_moving = random.random() > 0.3  # 70% chance driving
        self._active_dtcs: List[str] = []
        self._trip_duration = 0

    def step(self, fault_rate: float = 0.02) -> TelemetryEvent:
        """Advance vehicle state by 1 second and emit an event."""
        self.seq += 1
        now = datetime.now(timezone.utc).isoformat()

        # ── Movement simulation ────────────────────────────────────
        if self._is_moving:
            self._trip_duration += 1
            # Vary speed with acceleration/deceleration
            target_speed = random.gauss(50, 20)
            target_speed = max(0, min(120, target_speed))
            self.speed_kmh = 0.9 * self.speed_kmh + 0.1 * target_speed

            # Update position (approx: 1 deg lat ≈ 111km)
            dist_km = self.speed_kmh / 3600  # km per second
            heading_rad = math.radians(self.heading)
            self.lat += (dist_km / 111.0) * math.cos(heading_rad)
            self.lon += (dist_km / (111.0 * math.cos(math.radians(self.lat)))) * math.sin(heading_rad)

            # Heading drift
            self.heading = (self.heading + random.gauss(0, 5)) % 360

            # Update odometer
            self.odo_km += dist_km

            # Battery/fuel drain
            if self.soc_pct is not None:
                consumption = random.uniform(0.003, 0.008)  # % per second at speed
                self.soc_pct = max(5, self.soc_pct - consumption * (self.speed_kmh / 60))
                self.battery_temp_c = min(45, self.battery_temp_c + random.uniform(-0.1, 0.3))
            if self.fuel_pct is not None:
                self.fuel_pct = max(0, self.fuel_pct - random.uniform(0.0005, 0.002))

            if self.engine_rpm is not None:
                self.engine_rpm = int(random.gauss(1800, 400))
                self.engine_rpm = max(600, min(6000, self.engine_rpm))

            # Occasionally stop (trip end)
            if self._trip_duration > random.randint(300, 3600):
                self._is_moving = False
                self._trip_duration = 0
        else:
            # Parked / idle
            self.speed_kmh = 0
            self.engine_rpm = random.choice([None if self.fuel_type == "EV" else 750])
            if random.random() < 0.001:  # 0.1% chance to start moving
                self._is_moving = True

        # ── Fault/DTC injection ────────────────────────────────────
        if random.random() < fault_rate / 3600:  # fault_rate per vehicle per hour
            dtc = random.choice(OBD_DTCS_POOL)
            if dtc not in self._active_dtcs:
                self._active_dtcs.append(dtc)
        # Random DTC recovery
        if self._active_dtcs and random.random() < 0.0001:
            self._active_dtcs.pop(0)

        # ── Harsh event injection ──────────────────────────────────
        evt: Optional[str] = None
        if self._is_moving and random.random() < 0.002:  # 0.2% of moving events
            evt = random.choice(HARSH_EVENTS)

        return TelemetryEvent(
            vin=self.vin,
            ts=now,
            lat=round(self.lat, 6),
            lon=round(self.lon, 6),
            speed_kmh=round(self.speed_kmh, 1),
            soc_pct=round(self.soc_pct, 1) if self.soc_pct is not None else None,
            odo_km=round(self.odo_km, 1),
            dtc=list(self._active_dtcs),
            evt=evt,
            seq=self.seq,
            fuel_pct=round(self.fuel_pct, 1) if self.fuel_pct is not None else None,
            heading=round(self.heading, 1),
            altitude_m=round(self.altitude_m, 1),
            engine_rpm=self.engine_rpm,
            battery_temp_c=round(self.battery_temp_c, 1) if self.battery_temp_c is not None else None,
            tenant_id=self.tenant_id,
        )


# ── Kafka Publisher ─────────────────────────────────────────────────

async def emit_events_kafka(states: List[VehicleState],
                            batch_size: int = 500,
                            fault_rate: float = 0.02) -> None:
    """Emit telemetry events in batches to Kafka."""
    try:
        from confluent_kafka import Producer
    except ImportError:
        print("confluent-kafka not installed. Running in dry-run mode.")
        await emit_events_dryrun(states, batch_size, fault_rate)
        return

    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    producer = Producer({"bootstrap.servers": bootstrap, "queue.buffering.max.messages": 1_000_000})

    topic = "raw-telemetry"
    msg_count = 0
    start = time.monotonic()

    while True:
        tick_start = time.monotonic()

        for i in range(0, len(states), batch_size):
            batch = states[i:i + batch_size]
            for state in batch:
                event = state.step(fault_rate)
                payload = event.to_json().encode()
                producer.produce(topic, key=event.vin.encode(), value=payload)
                msg_count += 1

            producer.poll(0)

        producer.flush()
        elapsed = time.monotonic() - tick_start
        msg_per_sec = len(states) / max(elapsed, 0.001)

        if msg_count % 100_000 < batch_size:
            total_elapsed = time.monotonic() - start
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] "
                f"Emitted {msg_count:,} events | "
                f"{msg_per_sec:,.0f} events/sec | "
                f"Uptime: {total_elapsed:.0f}s"
            )

        # Sleep for remainder of 1-second tick
        sleep_time = max(0, 1.0 - elapsed)
        await asyncio.sleep(sleep_time)


async def emit_events_dryrun(states: List[VehicleState],
                              batch_size: int = 500,
                              fault_rate: float = 0.02) -> None:
    """Dry-run mode: print sample events to stdout."""
    tick = 0
    while tick < 5:
        tick += 1
        sample_count = 0
        for state in states[:batch_size]:
            event = state.step(fault_rate)
            if sample_count < 3:
                print(f"SAMPLE EVENT: {event.to_json()}")
                sample_count += 1
        print(f"Tick {tick}: Would emit {len(states):,} events to Kafka topic 'raw-telemetry'")
        await asyncio.sleep(1)


# ── Main entry point ────────────────────────────────────────────────

async def main():
    import argparse
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Motorq Vehicle Telemetry Simulator")
    parser.add_argument("--vehicles", type=int, default=1000, help="Number of vehicles to simulate")
    parser.add_argument("--fault-rate", type=float, default=0.02, help="Fault injection rate")
    parser.add_argument("--batch-size", type=int, default=500, help="Events per batch")
    parser.add_argument("--dry-run", action="store_true", help="Don't publish to Kafka")
    args = parser.parse_args()

    # Load fleet from JSON seed (or generate minimal set)
    fleet_file = "fleet_seed.json"
    if os.path.exists(fleet_file):
        with open(fleet_file) as f:
            fleet_data = json.load(f)
        print(f"Loaded {len(fleet_data):,} vehicles from {fleet_file}")
        fleet_data = fleet_data[:args.vehicles]
    else:
        print(f"No fleet_seed.json found. Generating {args.vehicles} vehicles inline...")
        from fleet_seeder import generate_fleet
        fleet = generate_fleet(args.vehicles)
        fleet_data = [v.to_dict() for v in fleet]

    print(f"Initializing {len(fleet_data):,} vehicle states...")
    states = [
        VehicleState(
            vin=v["vin"],
            home_lat=v["home_lat"],
            home_lon=v["home_lon"],
            fuel_type=v["fuel_type"],
            tenant_id=v["tenant_id"],
            odometer=v["odometer_km"],
        )
        for v in fleet_data
    ]

    print(f"Starting telemetry emission for {len(states):,} vehicles...")
    if args.dry_run:
        await emit_events_dryrun(states, args.batch_size, args.fault_rate)
    else:
        await emit_events_kafka(states, args.batch_size, args.fault_rate)


if __name__ == "__main__":
    asyncio.run(main())
