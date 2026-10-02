"""
Historical Parquet Seeder — generates 30 days of historical telemetry
for 100K vehicles and saves as partitioned Parquet files.

Used for:
  - Batch ML model training (predictive maintenance, driver scoring)
  - Historical analytics in the solution document
  - Populating cold storage tier (S3/HDFS equivalent)

Output structure:
  data/historical/
    year=2026/month=09/day=01/telemetry_part_000.parquet
    year=2026/month=09/day=02/telemetry_part_000.parquet
    ...
"""

import os
import random
import math
from datetime import datetime, timedelta, timezone
from typing import List
import json

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
    HAS_PYARROW = True
except ImportError:
    HAS_PYARROW = False
    print("pyarrow not available — will generate CSV instead")

HARSH_EVENTS = ["HARSH_BRAKE", "HARSH_ACCEL", "SHARP_TURN", "OVERSPEEDING", "IDLE_LONG", None]
DTCS_POOL = ["P0301", "P0171", "P0420", "P0442", "P0700", "C0035", "U0001", None]

OUTPUT_DIR = os.environ.get("HISTORICAL_OUTPUT_DIR", "data/historical")
VEHICLES_PER_CHUNK = 5000   # process in chunks to avoid OOM
EVENTS_PER_VEHICLE_PER_DAY = 3600  # 1/sec × 3600 seconds active per day


def _simulate_day_for_vehicle(vin: str, tenant_id: str, fuel_type: str,
                               home_lat: float, home_lon: float,
                               day_start: datetime, odometer_start: float,
                               has_fault: bool = False) -> List[dict]:
    """Generate telemetry events for one vehicle for one day (sampled)."""
    events = []
    lat, lon = home_lat + random.uniform(-0.05, 0.05), home_lon + random.uniform(-0.05, 0.05)
    soc = random.uniform(40, 100) if fuel_type == "EV" else None
    fuel = random.uniform(40, 100) if fuel_type != "EV" else None
    speed = 0.0
    odo = odometer_start
    heading = random.uniform(0, 360)
    is_moving = random.random() > 0.3

    # Sample every 60 seconds instead of 1 second to keep data manageable
    for minute in range(0, 1440, 1):  # every minute of the day
        ts = day_start + timedelta(minutes=minute)
        if is_moving:
            speed = max(0, min(120, random.gauss(55, 20)))
            dist_km = speed / 60  # km per minute
            heading += random.gauss(0, 3)
            heading %= 360
            rad = math.radians(heading)
            lat += (dist_km / 111.0) * math.cos(rad)
            lon += (dist_km / (111.0 * math.cos(math.radians(lat)))) * math.sin(rad)
            odo += dist_km
            if soc is not None:
                soc = max(5.0, soc - random.uniform(0.1, 0.3))
            if fuel is not None:
                fuel = max(0.0, fuel - random.uniform(0.05, 0.15))
            if random.random() < 0.0005:
                is_moving = False
        else:
            speed = 0.0
            if random.random() < 0.002:
                is_moving = True

        dtc = []
        if has_fault and random.random() < 0.3:
            dtc = [random.choice([d for d in DTCS_POOL if d])]

        evt = None
        if is_moving and random.random() < 0.001:
            evt = random.choice([e for e in HARSH_EVENTS if e])

        events.append({
            "time": ts.isoformat(),
            "vin": vin,
            "tenant_id": tenant_id,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "speed_kmh": round(speed, 1),
            "soc_pct": round(soc, 1) if soc else None,
            "fuel_pct": round(fuel, 1) if fuel else None,
            "odo_km": round(odo, 1),
            "heading": round(heading % 360, 1),
            "dtc": dtc,
            "evt": evt,
            "has_fault": has_fault,
        })

    return events


def generate_historical_data(
    fleet_file: str = "fleet_seed.json",
    days: int = 30,
    max_vehicles: int = 100_000,
    output_dir: str = OUTPUT_DIR,
    fault_vehicle_fraction: float = 0.05,  # 5% vehicles have recurring faults
) -> None:
    """Generate 30 days of historical telemetry and save as Parquet."""
    os.makedirs(output_dir, exist_ok=True)

    # Load fleet
    if os.path.exists(fleet_file):
        with open(fleet_file) as f:
            fleet = json.load(f)[:max_vehicles]
    else:
        print(f"Fleet file not found: {fleet_file}")
        return

    print(f"Generating {days} days of historical data for {len(fleet):,} vehicles...")
    print(f"Output: {output_dir}")

    end_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    days_list = [end_date - timedelta(days=d) for d in range(days, 0, -1)]

    # Mark fault vehicles
    fault_vins = set(v["vin"] for v in random.sample(fleet, int(len(fleet) * fault_vehicle_fraction)))
    print(f"Fault vehicles (recurring DTCs): {len(fault_vins):,}")

    for day_dt in days_list:
        day_str = day_dt.strftime("%Y-%m-%d")
        partition_path = os.path.join(
            output_dir,
            f"year={day_dt.year}",
            f"month={day_dt.month:02d}",
            f"day={day_dt.day:02d}",
        )
        os.makedirs(partition_path, exist_ok=True)
        out_file = os.path.join(partition_path, "telemetry.parquet")

        if os.path.exists(out_file):
            print(f"  {day_str}: already exists, skipping")
            continue

        all_events = []
        for i, vehicle in enumerate(fleet):
            has_fault = vehicle["vin"] in fault_vins
            events = _simulate_day_for_vehicle(
                vin=vehicle["vin"],
                tenant_id=vehicle["tenant_id"],
                fuel_type=vehicle["fuel_type"],
                home_lat=vehicle["home_lat"],
                home_lon=vehicle["home_lon"],
                day_start=day_dt,
                odometer_start=vehicle["odometer_km"],
                has_fault=has_fault,
            )
            all_events.extend(events)

            if (i + 1) % 10_000 == 0:
                print(f"  {day_str}: processed {i+1:,}/{len(fleet):,} vehicles, {len(all_events):,} events buffered")

        # Write to Parquet
        if HAS_PYARROW and all_events:
            schema = pa.schema([
                pa.field("time", pa.string()),
                pa.field("vin", pa.string()),
                pa.field("tenant_id", pa.string()),
                pa.field("lat", pa.float64()),
                pa.field("lon", pa.float64()),
                pa.field("speed_kmh", pa.float32()),
                pa.field("soc_pct", pa.float32()),
                pa.field("fuel_pct", pa.float32()),
                pa.field("odo_km", pa.float64()),
                pa.field("heading", pa.float32()),
                pa.field("evt", pa.string()),
                pa.field("has_fault", pa.bool_()),
            ])
            # Build columns
            table = pa.table({
                "time": [e["time"] for e in all_events],
                "vin": [e["vin"] for e in all_events],
                "tenant_id": [e["tenant_id"] for e in all_events],
                "lat": [e["lat"] for e in all_events],
                "lon": [e["lon"] for e in all_events],
                "speed_kmh": [e["speed_kmh"] for e in all_events],
                "soc_pct": [e["soc_pct"] for e in all_events],
                "fuel_pct": [e["fuel_pct"] for e in all_events],
                "odo_km": [e["odo_km"] for e in all_events],
                "heading": [e["heading"] for e in all_events],
                "evt": [e["evt"] for e in all_events],
                "has_fault": [e["has_fault"] for e in all_events],
            })
            pq.write_table(table, out_file, compression="snappy")
            size_mb = os.path.getsize(out_file) / (1024 * 1024)
            print(f"  {day_str}: wrote {len(all_events):,} events → {out_file} ({size_mb:.1f} MB)")
        else:
            # Fallback: write JSON
            json_file = out_file.replace(".parquet", ".json")
            with open(json_file, "w") as f:
                json.dump(all_events[:1000], f)  # sample only
            print(f"  {day_str}: wrote sample → {json_file}")

    print("\nHistorical seeding complete!")
    print(f"Output directory: {output_dir}")


if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--fleet-file", default="fleet_seed.json")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--vehicles", type=int, default=100_000)
    parser.add_argument("--output-dir", default=OUTPUT_DIR)
    args = parser.parse_args()

    generate_historical_data(
        fleet_file=args.fleet_file,
        days=args.days,
        max_vehicles=args.vehicles,
        output_dir=args.output_dir,
    )
