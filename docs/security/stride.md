# STRIDE Threat Model — Motorq Connected Vehicle Platform

## Overview
This document applies the **STRIDE** threat modelling framework to the Motorq platform.

| Category | Stands For | Example Threat |
|----------|-----------|---------------|
| **S** | Spoofing | Attacker impersonates a vehicle VIN to inject false telemetry |
| **T** | Tampering | MITM attack modifies telemetry data in transit |
| **R** | Repudiation | Driver denies causing a harsh braking event |
| **I** | Information Disclosure | Competitor reads a fleet's location data via broken auth |
| **D** | Denial of Service | Botnet floods ingestion endpoint at 10M events/sec |
| **E** | Elevation of Privilege | Driver role accesses fleet admin API endpoints |

---

## Asset Inventory

| Asset | Classification | Owner |
|-------|---------------|-------|
| Vehicle real-time location | High – PII/GDPR | Fleet tenant |
| DTC fault codes | Medium – Operational | OEM / Fleet |
| Driver safety scores | High – PII | Driver / Fleet |
| JWT signing secret | Critical – Auth | Platform |
| Kafka topics (raw-telemetry) | High – Operational | Platform |
| PostgreSQL fleet DB | High – Business critical | Platform |

---

## STRIDE Analysis Per Component

### 1. IoT Ingestion Service (FastAPI)

| Threat | Category | Severity | Mitigation |
|--------|----------|----------|------------|
| Attacker sends telemetry with forged VIN | **S** Spoofing | High | mTLS client certificates per vehicle; VIN validated against registered fleet DB |
| Payload contains SQLi or malicious JSON | **T** Tampering | High | Pydantic schema validation rejects unknown fields; parameterised SQL queries |
| Flood attack at 10x normal rate | **D** DoS | High | Per-VIN Redis sliding-window rate limiter; back-pressure with 429 response |
| Duplicate events inflate driver scores | **T** Tampering | Medium | Redis `(vin, seq)` deduplication with 5-min TTL |

**Mitigations implemented:** ✅ mTLS (`infra/certs/`), ✅ Pydantic validation, ✅ rate limiting, ✅ dedup

---

### 2. API Gateway (FastAPI)

| Threat | Category | Severity | Mitigation |
|--------|----------|----------|------------|
| Stolen JWT used to query another tenant's fleet | **E** Elevation | Critical | `tenant_id` extracted from JWT; all DB queries scoped to tenant |
| Driver role calls `/api/fleet` admin endpoint | **E** Elevation | High | RBAC `RoleChecker` dependency rejects unauthorised roles |
| Attacker injects SQL via query params | **T** Tampering | High | SQLAlchemy parameterised queries; no raw SQL concatenation |
| API response leaks PII to wrong tenant | **I** Disclosure | Critical | Multi-tenant isolation enforced at query layer |
| Broken access logs — attacker covers tracks | **R** Repudiation | Medium | Audit middleware logs every request to Kafka `audit-log` (immutable) |

**Mitigations implemented:** ✅ JWT+RBAC, ✅ tenant isolation, ✅ audit log, ✅ OWASP headers

---

### 3. Kafka Message Broker

| Threat | Category | Severity | Mitigation |
|--------|----------|----------|------------|
| Internal attacker reads raw-telemetry topic | **I** Disclosure | High | ACL per-service; ingestion can produce, stream processor can consume only |
| Compromised service publishes fake alerts | **T** Tampering | High | Schema Registry enforces Avro schema; malformed messages rejected |
| Broker crash drops unprocessed events | **D** DoS | Medium | Replication factor ≥ 3; min-ISR = 2 for ack |

---

### 4. AI Agent (LangGraph)

| Threat | Category | Severity | Mitigation |
|--------|----------|----------|------------|
| Prompt injection bypasses guardrails | **T** Tampering | High | Keyword injection detection + LLM self-check before tool execution |
| Agent queries another tenant's vehicle | **E** Elevation | Critical | All tool calls inject `tenant_id` from authenticated JWT |
| Agent dispatches maintenance without approval | **E** Elevation | High | HITL (Human-in-the-Loop) interrupt for destructive operations |
| Agent actions not logged | **R** Repudiation | High | Every tool call published to Kafka `audit-log` topic |

---

### 5. Frontend (Next.js)

| Threat | Category | Severity | Mitigation |
|--------|----------|----------|------------|
| XSS via malicious DTC text injected in alerts | **T** Tampering | High | React escapes by default; CSP header blocks inline scripts |
| Clickjacking of dashboard | **T** Tampering | Medium | `X-Frame-Options: DENY` header |
| Session token stolen via JS | **I** Disclosure | High | `HttpOnly` + `Secure` cookie for token storage (not localStorage) |

---

## Residual Risks & Accepted Trade-offs

| Risk | Acceptance Reason |
|------|------------------|
| No HSM for JWT signing key | Hackathon scope; production would use AWS KMS or Vault |
| Self-signed mTLS certs | Demo environment; production uses an internal PKI / ACM |
| Kafka ACLs not wired in docker-compose | Docker local dev; production Confluent Cloud has ACL enforcement |
