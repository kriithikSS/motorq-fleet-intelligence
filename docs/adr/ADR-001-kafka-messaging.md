# ADR-001: Kafka as the Central Message Broker

## Status
Accepted

## Context
The platform must ingest 100,000+ vehicle events per second reliably.
Events come from 100K+ simultaneous MQTT/HTTP connections with burst peaks of 3x at shift start.
We need:
- Durable storage with replay capability (re-process historical data for ML)
- Partitioned streams for parallel consumer scaling
- Ordered delivery per vehicle (VIN = partition key)
- At-least-once delivery with consumer-side idempotency

Alternatives evaluated:
- **RabbitMQ**: Excellent for task queues but lacks partitioned log storage and replay
- **AWS SQS/SNS**: Vendor lock-in; limited replay; closed to new customers (AWS IoT FleetWise example)
- **Pulsar**: Feature-comparable but less ecosystem maturity in our stack

## Decision
Use **Apache Kafka** (Confluent 7.6) as the central message broker.
- Topic `raw-telemetry`: 12 partitions, keyed by VIN → ordered per vehicle
- Topics `alerts`, `ml-events`, `driver-scores`: 6 partitions
- Topics `audit-log`, `dlq-events`: 3 partitions
- **Schema Registry** (Confluent) for Avro schema evolution
- Retention: 7 days for raw-telemetry; 30 days for audit-log

## Consequences
**Good:**
- Replay enables re-training ML models on historical data without re-ingestion
- Horizontal scaling: add partitions/consumers with no code change
- Exactly-once semantics available (Kafka Streams + transactional producers)
- Kafka UI provides operational visibility without extra tooling

**Bad:**
- Requires Zookeeper (or KRaft in newer versions) — extra operational component
- Consumer lag monitoring is essential to catch pipeline slowdowns
- Schema Registry adds a dependency to every producer/consumer

## CAP Trade-off
Raw telemetry: **AP** (availability + partition tolerance). A few duplicate or slightly delayed events are acceptable; ingestion must never block.
Audit log: **CP** (consistency + partition tolerance). Every access must be logged exactly once.
