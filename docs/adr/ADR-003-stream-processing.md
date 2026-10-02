# ADR-003: Spark Structured Streaming vs Flink for Real-time Processing

## Status
Accepted

## Context
Real-time event processing requirements:
- Detect DTC faults and harsh events within 5 seconds of arrival
- Sliding-window aggregates (5-minute windows, 1-minute slide)
- Watermarking for late-arriving events (MQTT reconnection storms)
- Geo-fence breach detection
- Must integrate with Kafka and PostgreSQL/MongoDB sinks

Alternatives evaluated:
- **Apache Flink**: Lower latency (true event-time processing, millisecond), native stateful processing
- **Spark Structured Streaming**: Higher latency (micro-batch, 1s minimum), but same Spark API for batch + stream
- **Kafka Streams**: JVM-only, tightly coupled to Kafka, no complex aggregations

## Decision
Use **Spark Structured Streaming** (PySpark 3.5) for stream processing.

**Primary reason**: The team uses Python throughout (FastAPI, ML engine). A single Spark cluster handles both the real-time stream (Structured Streaming) and the batch ML pipeline (Spark SQL on Parquet). This reduces infra cost and avoids a separate Flink cluster.

**Acceptable trade-off**: The 5-second alert latency target is achievable with 1-second micro-batch triggers. Flink's millisecond latency is not required at this stage.

**If latency requirements tighten** (< 1s SLA): migrate the alert-detection query to Flink; keep Spark for batch analytics.

## Consequences
**Good:**
- Unified API for stream + batch (same Python code, different `.readStream` / `.read`)
- Watermarking handles MQTT out-of-order delivery gracefully
- Native Kafka source/sink integration
- PySpark ML integration for real-time feature computation

**Bad:**
- Micro-batch introduces inherent latency floor (~1s processing + Kafka poll = 2-3s end-to-end)
- Spark checkpoint state can grow large for stateful operations at 100K events/sec
- Resource-heavy: Spark driver + executors require dedicated JVM memory
