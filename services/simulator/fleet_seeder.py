"""
Fleet Seeder — generates and seeds 100K simulated vehicles to PostgreSQL and MongoDB.
Produces realistic fleet with mixed OEM brands, vehicle types, and registration data.
"""

import asyncio
import json
import os
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import List

from vin_generator import WMIS, generate_vin_batch

# ── Vehicle metadata ────────────────────────────────────────────────

VEHICLE_MODELS = [
    # (make, model, type, fuel_type, battery_kWh)
    ("Honda", "CR-V", "SUV", "ICE", None),
    ("Honda", "Accord", "Sedan", "Hybrid", None),
    ("Ford", "F-150", "Truck", "ICE", None),
    ("Ford", "Mustang Mach-E", "SUV", "EV", 91.0),
    ("Chevrolet", "Bolt EV", "Hatchback", "EV", 65.0),
    ("Nissan", "Leaf", "Hatchback", "EV", 62.0),
    ("Toyota", "Camry", "Sedan", "Hybrid", None),
    ("Toyota", "RAV4", "SUV", "Hybrid", None),
    ("Volkswagen", "ID.4", "SUV", "EV", 82.0),
    ("Volvo", "XC90", "SUV", "Hybrid", None),
    ("Volvo", "C40 Recharge", "SUV", "EV", 78.0),
    ("Hyundai", "IONIQ 6", "Sedan", "EV", 77.4),
    ("Kia", "EV6", "Crossover", "EV", 77.4),
    ("Land Rover", "Defender", "SUV", "ICE", None),
    ("Renault", "Zoe", "Hatchback", "EV", 52.0),
    ("Alfa Romeo", "Stelvio", "SUV", "ICE", None),
    ("Chrysler", "Pacifica", "Minivan", "Hybrid", None),
    ("Subaru", "Outback", "Wagon", "ICE", None),
]

FLEET_TYPES = ["commercial", "rental", "private", "government", "emergency"]
REGIONS = [
    # (name, lat_center, lon_center, radius_deg)
    ("Mumbai", 19.076, 72.877, 0.5),
    ("Delhi", 28.704, 77.102, 0.5),
    ("Bangalore", 12.971, 77.594, 0.4),
    ("Chennai", 13.083, 80.270, 0.4),
    ("Hyderabad", 17.385, 78.487, 0.4),
    ("Pune", 18.520, 73.856, 0.3),
    ("Kolkata", 22.573, 88.364, 0.3),
    ("Ahmedabad", 23.023, 72.572, 0.3),
]

OBD_DTCS = [
    "P0100", "P0101", "P0102", "P0110", "P0120", "P0130",
    "P0171", "P0174", "P0200", "P0300", "P0301", "P0302",
    "P0400", "P0420", "P0442", "P0500", "P0700", "P1000",
    "C0035", "C0040", "C0045", "U0001", "U0100", "U0121",
    "B0001", "B0020",
]


@dataclass
class Vehicle:
    vin: str
    make: str
    model: str
    vehicle_type: str
    fuel_type: str
    battery_kwh: float | None
    year: int
    color: str
    fleet_type: str
    tenant_id: str
    driver_id: str
    region: str
    home_lat: float
    home_lon: float
    registered_at: str
    odometer_km: float
    last_seen: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _random_home_location(region: dict) -> tuple[float, float]:
    """Generate a random lat/lon near a region center."""
    lat = region["lat"] + random.uniform(-region["radius"], region["radius"])
    lon = region["lon"] + random.uniform(-region["radius"], region["radius"])
    return round(lat, 6), round(lon, 6)


def generate_fleet(num_vehicles: int = 100_000) -> List[Vehicle]:
    """Generate a fleet of simulated vehicles."""
    print(f"Generating {num_vehicles:,} VINs...")
    vins = generate_vin_batch(num_vehicles)

    colors = ["White", "Black", "Silver", "Gray", "Blue", "Red", "Green", "Brown", "Orange"]
    tenants = [f"tenant_{i:04d}" for i in range(1, 51)]  # 50 tenant companies

    vehicles = []
    region_list = [
        {"name": r[0], "lat": r[1], "lon": r[2], "radius": r[3]}
        for r in REGIONS
    ]

    for i, vin in enumerate(vins):
        model_data = VEHICLE_MODELS[i % len(VEHICLE_MODELS)]
        make, model, vtype, fuel, battery = model_data
        year = random.randint(2020, 2026)
        region = random.choice(region_list)
        home_lat, home_lon = _random_home_location(region)
        registered_at = datetime.utcnow() - timedelta(
            days=random.randint(30, 1460)
        )
        odometer = random.uniform(0, 150_000)

        v = Vehicle(
            vin=vin,
            make=make,
            model=model,
            vehicle_type=vtype,
            fuel_type=fuel,
            battery_kwh=battery,
            year=year,
            color=random.choice(colors),
            fleet_type=random.choice(FLEET_TYPES),
            tenant_id=random.choice(tenants),
            driver_id=f"DRV-{random.randint(10000, 99999)}",
            region=region["name"],
            home_lat=home_lat,
            home_lon=home_lon,
            registered_at=registered_at.isoformat(),
            odometer_km=round(odometer, 1),
        )
        vehicles.append(v)

        if (i + 1) % 10_000 == 0:
            print(f"  Generated {i+1:,}/{num_vehicles:,} vehicles...")

    return vehicles


async def seed_postgres(vehicles: List[Vehicle]) -> None:
    """Seed vehicles into PostgreSQL."""
    try:
        import asyncpg
    except ImportError:
        print("asyncpg not installed, skipping Postgres seed")
        return

    db_url = os.environ.get("DATABASE_URL", "postgresql://motorq:motorq_secret@localhost:5432/motorq")
    conn = await asyncpg.connect(db_url)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS vehicles (
            vin VARCHAR(17) PRIMARY KEY,
            make VARCHAR(50) NOT NULL,
            model VARCHAR(100) NOT NULL,
            vehicle_type VARCHAR(50),
            fuel_type VARCHAR(20),
            battery_kwh NUMERIC(6,2),
            year SMALLINT,
            color VARCHAR(30),
            fleet_type VARCHAR(30),
            tenant_id VARCHAR(50) NOT NULL,
            driver_id VARCHAR(50),
            region VARCHAR(50),
            home_lat NUMERIC(9,6),
            home_lon NUMERIC(9,6),
            registered_at TIMESTAMPTZ,
            odometer_km NUMERIC(10,1),
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    print("Seeding PostgreSQL in batches...")
    batch_size = 1000
    for i in range(0, len(vehicles), batch_size):
        batch = vehicles[i:i + batch_size]
        await conn.executemany(
            """
            INSERT INTO vehicles
              (vin, make, model, vehicle_type, fuel_type, battery_kwh, year, color,
               fleet_type, tenant_id, driver_id, region, home_lat, home_lon,
               registered_at, odometer_km)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
            ON CONFLICT (vin) DO NOTHING
            """,
            [
                (
                    v.vin, v.make, v.model, v.vehicle_type, v.fuel_type,
                    v.battery_kwh, v.year, v.color, v.fleet_type, v.tenant_id,
                    v.driver_id, v.region, v.home_lat, v.home_lon,
                    v.registered_at, v.odometer_km,
                )
                for v in batch
            ],
        )
        if (i // batch_size + 1) % 20 == 0:
            print(f"  PostgreSQL: inserted {min(i + batch_size, len(vehicles)):,}/{len(vehicles):,}")

    await conn.close()
    print("PostgreSQL seeding complete!")


async def seed_mongo(vehicles: List[Vehicle]) -> None:
    """Seed vehicle metadata into MongoDB."""
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
    except ImportError:
        print("motor not installed, skipping MongoDB seed")
        return

    mongo_uri = os.environ.get("MONGO_URI", "mongodb://motorq:motorq_secret@localhost:27017/telemetry?authSource=admin")
    client = AsyncIOMotorClient(mongo_uri)
    db = client["telemetry"]
    collection = db["vehicles"]

    # Create indexes
    await collection.create_index("vin", unique=True)
    await collection.create_index("tenant_id")
    await collection.create_index("region")
    await collection.create_index("fuel_type")

    print("Seeding MongoDB in batches...")
    batch_size = 2000
    for i in range(0, len(vehicles), batch_size):
        batch = [v.to_dict() for v in vehicles[i:i + batch_size]]
        try:
            await collection.insert_many(batch, ordered=False)
        except Exception:
            pass  # ignore duplicate key errors
        if (i // batch_size + 1) % 10 == 0:
            print(f"  MongoDB: inserted {min(i + batch_size, len(vehicles)):,}/{len(vehicles):,}")

    client.close()
    print("MongoDB seeding complete!")


def save_to_json(vehicles: List[Vehicle], path: str = "fleet_seed.json") -> None:
    """Save fleet to a JSON file for reference."""
    with open(path, "w") as f:
        json.dump([v.to_dict() for v in vehicles], f, indent=2)
    print(f"Fleet saved to {path}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=100_000)
    parser.add_argument("--output", type=str, default="fleet_seed.json")
    parser.add_argument("--seed-pg", action="store_true")
    parser.add_argument("--seed-mongo", action="store_true")
    args = parser.parse_args()

    fleet = generate_fleet(args.count)
    save_to_json(fleet, args.output)

    if args.seed_pg or args.seed_mongo:
        from dotenv import load_dotenv
        load_dotenv()
        tasks = []
        if args.seed_pg:
            tasks.append(seed_postgres(fleet))
        if args.seed_mongo:
            tasks.append(seed_mongo(fleet))
        async def run_seeds():
            await asyncio.gather(*tasks)
        asyncio.run(run_seeds())
