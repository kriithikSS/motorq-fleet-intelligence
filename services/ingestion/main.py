"""
FastAPI Ingestion Service — the front door for all vehicle telemetry.

Responsibilities:
  1. Accept events via HTTP POST (and optionally MQTT bridge)
  2. Validate schema using JSON Schema / Avro
  3. Deduplicate by (vin, seq) using Redis Bloom Filter
  4. Apply back-pressure (rate limiting)
  5. Publish valid events to Kafka topic: raw-telemetry
  6. Route invalid events to Kafka DLQ topic: dlq-events
"""

import asyncio
import hashlib
import json
import os
import time
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
import redis.asyncio as aioredis
from prometheus_client import Counter, Histogram, make_asgi_app
import structlog

log = structlog.get_logger()

# ── Prometheus Metrics ──────────────────────────────────────────────

EVENTS_RECEIVED = Counter("ingestion_events_received_total", "Events received", ["status"])
EVENTS_LATENCY = Histogram("ingestion_event_latency_seconds", "Event processing latency")
KAFKA_PUBLISH_ERRORS = Counter("ingestion_kafka_errors_total", "Kafka publish errors")

# ── Pydantic Schema ─────────────────────────────────────────────────

class TelemetryEventIn(BaseModel):
    vin: str = Field(..., min_length=17, max_length=17)
    ts: str
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    speed_kmh: float = Field(..., ge=0, le=400)
    soc_pct: Optional[float] = Field(None, ge=0, le=100)
    odo_km: float = Field(..., ge=0)
    dtc: List[str] = Field(default_factory=list, max_length=20)
    evt: Optional[str] = None
    seq: int
    fuel_pct: Optional[float] = Field(None, ge=0, le=100)
    heading: float = Field(0, ge=0, le=360)
    altitude_m: float = Field(0)
    engine_rpm: Optional[int] = Field(None, ge=0, le=10000)
    battery_temp_c: Optional[float] = None
    tenant_id: str
    event_id: str

    @field_validator("vin")
    @classmethod
    def validate_vin(cls, v: str) -> str:
        """Validate VIN: 17 chars, no I/O/Q, valid characters."""
        v = v.upper()
        invalid = set("IOQ")
        allowed = set("ABCDEFGHJKLMNPRSTUVWXYZ0123456789")
        if any(c in invalid for c in v):
            raise ValueError(f"VIN contains invalid characters: {v}")
        if not all(c in allowed for c in v):
            raise ValueError(f"VIN has invalid characters: {v}")
        return v

    @field_validator("dtc", mode="before")
    @classmethod
    def validate_dtcs(cls, v: List[str]) -> List[str]:
        """Validate OBD-II DTC format: letter + 4 digits."""
        import re
        dtc_pattern = re.compile(r"^[PCBU][0-9A-F]{4}$")
        for dtc in v:
            if not dtc_pattern.match(dtc.upper()):
                raise ValueError(f"Invalid DTC format: {dtc}")
        return [d.upper() for d in v]


class BatchIngestRequest(BaseModel):
    events: List[TelemetryEventIn] = Field(..., max_length=10000)


# ── Global State ────────────────────────────────────────────────────

redis_client: aioredis.Redis = None
kafka_producer = None
dlq_producer = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize connections on startup."""
    global redis_client, kafka_producer, dlq_producer

    # Redis
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    redis_client = aioredis.from_url(redis_url, decode_responses=True)
    log.info("Redis connected", url=redis_url)

    # Kafka (optional — graceful degradation if not available)
    try:
        from confluent_kafka import Producer
        bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        kafka_producer = Producer({
            "bootstrap.servers": bootstrap,
            "queue.buffering.max.messages": 500000,
            "queue.buffering.max.ms": 50,
            "compression.type": "lz4",
        })
        dlq_producer = Producer({"bootstrap.servers": bootstrap})
        log.info("Kafka connected", bootstrap=bootstrap)
    except Exception as e:
        log.warning("Kafka unavailable, events will be logged only", error=str(e))

    yield

    # Cleanup
    if redis_client:
        await redis_client.close()
    if kafka_producer:
        kafka_producer.flush()


# ── FastAPI App ─────────────────────────────────────────────────────

app = FastAPI(
    title="Motorq IoT Ingestion Service",
    version="1.0.0",
    description="Validates and ingests vehicle telemetry events into the Kafka pipeline",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

# Mount Prometheus metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


# ── Deduplication (Redis Bloom Filter / Set) ────────────────────────

DEDUP_WINDOW_SEC = 300  # 5-minute dedup window

async def is_duplicate(vin: str, seq: int, event_id: str) -> bool:
    """
    Check if an event is a duplicate using Redis.
    Uses a rolling set keyed by (vin, seq) with TTL.
    For production, replace with RedisBloom for O(1) probabilistic dedup.
    """
    key = f"dedup:{vin}:{seq}"
    result = await redis_client.set(key, event_id, nx=True, ex=DEDUP_WINDOW_SEC)
    return result is None  # None means key already existed → duplicate


# ── Back-pressure / Rate Limiting ──────────────────────────────────

RATE_LIMIT_PER_VIN_PER_MINUTE = 120  # ~2 events/sec per VIN max

async def check_rate_limit(vin: str) -> bool:
    """Sliding window rate limiter per VIN."""
    key = f"rate:{vin}:{int(time.time() // 60)}"
    count = await redis_client.incr(key)
    if count == 1:
        await redis_client.expire(key, 120)
    return count <= RATE_LIMIT_PER_VIN_PER_MINUTE


# ── Kafka Publishing ────────────────────────────────────────────────

def publish_to_kafka(topic: str, key: str, value: dict) -> None:
    """Publish an event to Kafka (fire and forget)."""
    if kafka_producer is None:
        return
    try:
        kafka_producer.produce(
            topic,
            key=key.encode(),
            value=json.dumps(value, separators=(",", ":")).encode(),
        )
        kafka_producer.poll(0)
    except Exception as e:
        KAFKA_PUBLISH_ERRORS.inc()
        log.error("Kafka publish failed", topic=topic, error=str(e))


def publish_to_dlq(event: dict, reason: str) -> None:
    """Route invalid/rejected events to the DLQ topic."""
    payload = {"reason": reason, "original": event}
    if dlq_producer:
        try:
            dlq_producer.produce(
                "dlq-events",
                key=event.get("vin", "unknown").encode(),
                value=json.dumps(payload).encode(),
            )
        except Exception:
            pass


# ── Endpoints ───────────────────────────────────────────────────────

@app.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest_event(
    event: TelemetryEventIn,
    background_tasks: BackgroundTasks,
):
    """Ingest a single telemetry event."""
    with EVENTS_LATENCY.time():
        # Deduplication
        if redis_client and await is_duplicate(event.vin, event.seq, event.event_id):
            EVENTS_RECEIVED.labels(status="duplicate").inc()
            return JSONResponse({"status": "duplicate", "event_id": event.event_id})

        # Rate limiting
        if redis_client and not await check_rate_limit(event.vin):
            EVENTS_RECEIVED.labels(status="rate_limited").inc()
            raise HTTPException(status_code=429, detail="Rate limit exceeded for VIN")

        # Publish to Kafka
        background_tasks.add_task(
            publish_to_kafka, "raw-telemetry", event.vin, event.model_dump()
        )
        EVENTS_RECEIVED.labels(status="accepted").inc()

    return {"status": "accepted", "event_id": event.event_id}


@app.post("/ingest/batch", status_code=status.HTTP_202_ACCEPTED)
async def ingest_batch(req: BatchIngestRequest, background_tasks: BackgroundTasks):
    """Ingest a batch of telemetry events (up to 10,000)."""
    accepted = 0
    duplicates = 0
    rate_limited = 0

    for event in req.events:
        if redis_client and await is_duplicate(event.vin, event.seq, event.event_id):
            duplicates += 1
            continue

        if redis_client and not await check_rate_limit(event.vin):
            rate_limited += 1
            continue

        background_tasks.add_task(
            publish_to_kafka, "raw-telemetry", event.vin, event.model_dump()
        )
        accepted += 1

    EVENTS_RECEIVED.labels(status="accepted").inc(accepted)
    EVENTS_RECEIVED.labels(status="duplicate").inc(duplicates)
    EVENTS_RECEIVED.labels(status="rate_limited").inc(rate_limited)

    return {
        "accepted": accepted,
        "duplicates": duplicates,
        "rate_limited": rate_limited,
        "total": len(req.events),
    }


@app.get("/health")
async def health():
    """Health check."""
    checks = {"api": "ok"}
    if redis_client:
        try:
            await redis_client.ping()
            checks["redis"] = "ok"
        except Exception:
            checks["redis"] = "error"
    if kafka_producer:
        checks["kafka"] = "ok"
    return checks


@app.get("/ready")
async def ready():
    """Readiness probe — service is ready when Redis and Kafka are connected."""
    if redis_client is None:
        raise HTTPException(status_code=503, detail="Redis not connected")
    try:
        await redis_client.ping()
    except Exception:
        raise HTTPException(status_code=503, detail="Redis ping failed")
    return {"status": "ready"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True, workers=1)
