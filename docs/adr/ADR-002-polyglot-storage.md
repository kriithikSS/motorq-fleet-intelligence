# ADR-002: Polyglot Storage — PostgreSQL + TimescaleDB + MongoDB + Redis + Elasticsearch + Qdrant

## Status
Accepted

## Context
Vehicle data has fundamentally different shapes and access patterns:
- **Fleet metadata** (vehicles, drivers, subscriptions): structured, relational, ACID required
- **Time-series telemetry**: billions of rows, time-range queries, aggregations
- **Raw event documents**: schemaless, per-vehicle, recent-history lookups
- **Cache**: sub-millisecond vehicle state lookups for dashboard
- **Search / logs**: full-text search on DTCs, alert descriptions
- **AI/Semantic**: embedding-based similarity search for agent context

A single SQL database fails at this scale (see §4.1 of the problem statement).

## Decision

| Data | Store | Justification |
|------|-------|--------------|
| Fleet, Driver, Trip, Alert, Subscription, Audit | **PostgreSQL 16 (ACID)** | Relational integrity required. Billing needs CP consistency. |
| Telemetry (hot: 7 days) | **TimescaleDB hypertable** | Time-series hypertable with chunk partitioning; continuous aggregates replace expensive GROUP BY queries |
| Telemetry (cold: > 7 days) | **Parquet on S3/local disk** | Column storage, Snappy compression, Spark-readable for batch ML |
| Raw IoT events | **MongoDB** | Schemaless → OEM format differences without migrations; per-VIN latest-state document |
| Vehicle state cache / rate limits / pub-sub | **Redis** | O(1) reads, TTL-based dedup, pub-sub for WebSocket fan-out |
| Log analytics / DTC full-text search | **Elasticsearch** | Inverted index for code + text search; Kibana dashboards |
| Agent semantic context | **Qdrant** | Vector similarity search over alert/trip embeddings for AI agent |

## Consequences
**Good:**
- Each store optimized for its access pattern → better performance per query
- TimescaleDB continuous aggregates cut dashboard query time by ~10–50x
- MongoDB schemaless format handles new OEM fields without downtime
- Qdrant enables semantic fleet queries the AI agent couldn't do with SQL alone

**Bad:**
- 6 storage systems = higher operational burden
- Cross-store joins must be done at the application layer
- Data consistency across stores is eventual (telemetry in Mongo + Postgres may diverge by seconds)

## CAP Trade-offs Per Store
- PostgreSQL: **CP** — billing and audit must be strongly consistent
- TimescaleDB hot: **CP** — recent telemetry must be accurate for dashboards
- MongoDB raw: **AP** — a few missing/duplicate events acceptable; ingestion must not block
- Redis: **AP** — cache misses fall back to DB; stale cache acceptable for 30-60s
- Elasticsearch: **AP** — search index may lag by seconds behind the write path
