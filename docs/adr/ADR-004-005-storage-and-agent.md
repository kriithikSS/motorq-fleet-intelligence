# ADR-004: Hot / Warm / Cold Storage Lifecycle

## Status
Accepted

## Context
Raw telemetry volume: ~8.6 TB/day → ~3 PB/year. Storing all data in PostgreSQL or MongoDB indefinitely is cost-prohibitive and degrades query performance. A tiered storage strategy is needed.

## Decision

| Tier | Storage | Retention | Access Pattern | Cost |
|------|---------|-----------|---------------|------|
| **Hot** | TimescaleDB hypertable (SSD) | 7 days | Real-time dashboard, alert correlation | High |
| **Warm** | MongoDB (HDD/SSD) | 90 days | Recent history queries, per-vehicle lookups | Medium |
| **Cold** | Parquet on S3 / local HDFS (HDD) | 3 years | Batch ML training, compliance audit | Low |
| **Deleted** | — | > 3 years | Per GDPR/DPDP right-to-erasure | — |

**Data movement:**
- TimescaleDB retention policy auto-drops chunks older than 7 days (but data is already in Parquet before this)
- Nightly Spark job: reads Kafka → writes Parquet partitioned by `year/month/day`
- Warm → Cold: MongoDB TTL index deletes documents older than 90 days

**Query routing:**
- Last 7 days → TimescaleDB (millisecond query time via hypertable indexes)
- Last 90 days → MongoDB (document-level queries with VIN index)
- > 90 days → Spark on Parquet (minutes for full scans)

## Consequences
**Good:**
- 95% cost reduction vs storing everything in TimescaleDB
- Compliance: Parquet retention + erasure support for GDPR right-to-erasure
- ML training data always available in Spark-optimized Parquet format
- Hot tier stays small → queries stay fast

**Bad:**
- Queries spanning tiers require application-layer data merging
- Erasure (right-to-delete) requires re-writing Parquet files → non-trivial operational process
- Cold storage query latency (minutes) not suitable for real-time dashboards

# ADR-005: LangGraph for Agentic AI Layer

## Status
Accepted

## Context
Fleet operators need to query complex data using natural language ("which vehicles will break down this week?"). This requires:
- Tool-calling to query multiple data stores
- Multi-step reasoning (fetch vehicle → check alerts → run prediction)
- Audit trail for every AI action
- Guardrails against prompt injection and unauthorized data access
- Multi-LLM support (swap providers if credits are exhausted)

## Decision
Use **LangGraph** (built on LangChain) for the agent framework.

**LLM Provider strategy**: Abstract via `LLM_PROVIDER` + `LLM_MODEL` environment variables. Supports OpenAI, Anthropic (Claude), and Google (Gemini). Switch by changing `.env` — no code change needed.

**Tools**: 5 MCP-compatible tools scoped by tenant_id: `query_fleet`, `get_vehicle_detail`, `get_driver_score`, `search_alerts`, `predict_maintenance`.

**Guardrails:**
1. Prompt injection detection (keyword-based + LLM self-check)
2. Tool permission scoping by RBAC role
3. Human-in-the-loop approval for high-risk actions (maintenance dispatch)
4. Full audit trail: every tool call logged to Kafka `audit-log` topic

**Cost per query**: ~$0.002–$0.01 (GPT-4o-mini / Gemini Flash 2.0)
**Latency per query**: ~1–3 seconds (including tool calls)

## Consequences
**Good:**
- Natural-language fleet Q&A accessible to non-technical fleet managers
- LLM provider is interchangeable → no single-point API cost dependency
- LangGraph's stateful graph enables multi-step reasoning with branching
- Audit trail satisfies compliance requirement for AI agent actions

**Bad:**
- LLM hallucination risk — mitigated by grounding every answer in tool-returned data
- API cost at scale (if agents are triggered frequently)
- LangGraph adds ~300ms overhead vs direct API calls for simple queries
