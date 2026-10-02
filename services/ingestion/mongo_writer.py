"""
MongoDB Telemetry Writer — consumes from Kafka 'raw-telemetry' topic
and writes raw events to MongoDB for document-oriented queries.

MongoDB is used for:
  - Raw event storage per vehicle (latest state + recent history)
  - Per-VIN document with embedded recent telemetry array
  - OEM-specific payload flexibility (schemaless)
  - Fast latest-state lookups without TimescaleDB hypertable query overhead
"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import List

import structlog

log = structlog.get_logger()


async def consume_and_write(
    kafka_bootstrap: str,
    mongo_uri: str,
    batch_size: int = 500,
    commit_interval_sec: float = 2.0,
) -> None:
    """Consume from Kafka and write to MongoDB in batches."""
    try:
        from confluent_kafka import Consumer, KafkaError
        from motor.motor_asyncio import AsyncIOMotorClient
    except ImportError as e:
        print(f"Missing dependency: {e}. Install confluent-kafka and motor.")
        return

    # ── MongoDB setup ─────────────────────────────────────────────────
    client = AsyncIOMotorClient(mongo_uri)
    db = client["telemetry"]
    raw_events = db["raw_events"]          # all events (recent window)
    vehicle_state = db["vehicle_state"]    # latest state per vehicle

    # Create indexes
    await raw_events.create_index([("vin", 1), ("ts", -1)])
    await raw_events.create_index("tenant_id")
    await raw_events.create_index("evt", sparse=True)
    await raw_events.create_index("dtc", sparse=True)
    await vehicle_state.create_index("vin", unique=True)
    await vehicle_state.create_index("tenant_id")

    log.info("MongoDB indexes ready")

    # ── Kafka consumer ────────────────────────────────────────────────
    consumer = Consumer({
        "bootstrap.servers": kafka_bootstrap,
        "group.id": "mongo-writer",
        "auto.offset.reset": "latest",
        "enable.auto.commit": False,
        "max.poll.interval.ms": 300_000,
        "session.timeout.ms": 60_000,
    })
    consumer.subscribe(["raw-telemetry"])

    log.info("Kafka consumer subscribed to raw-telemetry")

    batch: List[dict] = []
    last_commit = time.monotonic()
    total_written = 0

    try:
        while True:
            msg = consumer.poll(timeout=0.1)

            if msg is None:
                # Flush batch on timeout
                if batch and (time.monotonic() - last_commit) >= commit_interval_sec:
                    await _flush_batch(batch, raw_events, vehicle_state)
                    total_written += len(batch)
                    consumer.commit(asynchronous=False)
                    log.info("Batch flushed", count=len(batch), total=total_written)
                    batch = []
                    last_commit = time.monotonic()
                continue

            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                log.error("Kafka error", error=msg.error())
                continue

            try:
                event = json.loads(msg.value().decode())
                batch.append(event)
            except json.JSONDecodeError as e:
                log.warning("Invalid JSON", error=str(e))
                continue

            if len(batch) >= batch_size:
                await _flush_batch(batch, raw_events, vehicle_state)
                total_written += len(batch)
                consumer.commit(asynchronous=False)
                if total_written % 10_000 < batch_size:
                    log.info("Progress", total_written=total_written)
                batch = []
                last_commit = time.monotonic()

    except KeyboardInterrupt:
        log.info("Shutting down Mongo writer...")
    finally:
        if batch:
            await _flush_batch(batch, raw_events, vehicle_state)
        consumer.close()
        client.close()


async def _flush_batch(
    batch: List[dict],
    raw_events,
    vehicle_state,
) -> None:
    """Write batch to MongoDB: raw events + update vehicle state."""
    now = datetime.now(timezone.utc).isoformat()

    # ── Write raw events ──────────────────────────────────────────────
    docs = []
    state_updates = {}

    for event in batch:
        doc = {
            "vin": event.get("vin"),
            "ts": event.get("ts"),
            "tenant_id": event.get("tenant_id"),
            "lat": event.get("lat"),
            "lon": event.get("lon"),
            "speed_kmh": event.get("speed_kmh"),
            "soc_pct": event.get("soc_pct"),
            "fuel_pct": event.get("fuel_pct"),
            "odo_km": event.get("odo_km"),
            "dtc": event.get("dtc", []),
            "evt": event.get("evt"),
            "seq": event.get("seq"),
            "battery_temp_c": event.get("battery_temp_c"),
            "engine_rpm": event.get("engine_rpm"),
            "event_id": event.get("event_id"),
            "ingested_at": now,
        }
        docs.append(doc)

        # Track latest state per VIN
        vin = event.get("vin")
        if vin not in state_updates or event.get("ts", "") > state_updates[vin].get("ts", ""):
            state_updates[vin] = {
                "vin": vin,
                "tenant_id": event.get("tenant_id"),
                "lat": event.get("lat"),
                "lon": event.get("lon"),
                "speed_kmh": event.get("speed_kmh"),
                "soc_pct": event.get("soc_pct"),
                "odo_km": event.get("odo_km"),
                "dtc": event.get("dtc", []),
                "evt": event.get("evt"),
                "last_seen": event.get("ts"),
                "updated_at": now,
            }

    # Bulk insert raw events (unordered for speed)
    if docs:
        try:
            await raw_events.insert_many(docs, ordered=False)
        except Exception:
            pass  # ignore duplicate event_id conflicts

    # Upsert vehicle state
    for vin, state in state_updates.items():
        try:
            await vehicle_state.update_one(
                {"vin": vin},
                {"$set": state},
                upsert=True,
            )
        except Exception:
            pass


async def main():
    from dotenv import load_dotenv
    load_dotenv()

    kafka_bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    mongo_uri = os.environ.get("MONGO_URI", "mongodb://motorq:motorq_secret@localhost:27017/telemetry?authSource=admin")

    print(f"Starting MongoDB writer...")
    print(f"  Kafka: {kafka_bootstrap}")
    print(f"  MongoDB: {mongo_uri[:40]}...")

    await consume_and_write(kafka_bootstrap, mongo_uri)


if __name__ == "__main__":
    asyncio.run(main())
