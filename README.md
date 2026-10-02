# Motorq Connected Vehicle Intelligence Platform

## 🚗 Problem Space
**Predictive Maintenance + Driver Safety Scoring + Real-time Telemetry Pipeline**

A production-grade connected vehicle intelligence platform simulating 100,000+ vehicles,
detecting maintenance risks before breakdowns, scoring driver safety in real time, and
providing an AI agent interface for fleet operators.

---

## 🚀 Quick Start (One Command)

```bash
# 1. Clone and configure
cp .env.example .env
# (edit .env with your secrets)

# 2. Start all infrastructure
cd infra && docker compose up -d

# 3. Seed 100K vehicles
cd services/simulator
pip install -r ../../requirements.txt
python fleet_seeder.py --count 100000 --seed-pg --seed-mongo

# 4. Start the telemetry simulator
python event_emitter.py --vehicles 100000

# 5. Start the API gateway
cd ../api-gateway && uvicorn main:app --port 8000

# 6. Start the frontend
cd ../../frontend && npm install && npm run dev
```

Open http://localhost:3000 for the dashboard.

---

## 🏗️ Architecture

```
100K Vehicles → MQTT/HTTP → Ingestion (FastAPI) → Kafka → Spark Streaming
                                                       ↓
                                          PostgreSQL/TimescaleDB (3NF, hot 7 days)
                                          MongoDB (raw telemetry docs)
                                          Redis (cache + rate limit)
                                          Elasticsearch (logs + search)
                                          Qdrant (vector store, agent)
                                               ↓
                              FastAPI API Gateway → Next.js Dashboard
                              LangGraph AI Agent (fleet Q&A)
```

## 📁 Repository Structure

```
motorq/
├── services/
│   ├── simulator/       # 100K vehicle data generator
│   ├── ingestion/       # FastAPI: validates + routes to Kafka
│   ├── stream-processor/ # Spark: real-time detection
│   ├── ml-engine/       # Predictive maintenance + driver scoring
│   ├── api-gateway/     # FastAPI: unified REST + WebSocket API
│   └── agent/           # LangGraph agentic AI
├── frontend/            # Next.js dashboard
├── infra/               # Docker, K8s, Terraform, Prometheus, Grafana
├── tests/               # Unit, integration, performance, security
└── docs/                # Architecture, ADRs, ER diagrams
```

## 🧪 Running Tests

```bash
# Unit tests with coverage
pytest tests/unit/ --cov=services --cov-report=html

# Integration tests (requires Docker)
pytest tests/integration/

# Load test (100K events/sec)
cd tests/performance && locust -f locustfile.py --headless -u 1000 -r 100
```

## 🔐 Security

- OAuth2/OIDC + JWT for API auth
- RBAC with tenant isolation
- mTLS for device-to-ingestion
- AES-256 at rest, TLS 1.3 in transit
- Full audit trail (every data access logged)
- GDPR/DPDP: location masking + right-to-erasure

## 📊 Non-Functional Targets

| NFR | Target |
|-----|--------|
| Ingest throughput | 100,000+ events/sec |
| End-to-end latency | < 2s dashboard, < 5s alert |
| API latency | p95 < 200ms, p99 < 500ms |
| Availability | 99.9%, no single point of failure |

## 🔧 Environment Variables

See [`.env.example`](.env.example) for all required configuration.

## 📹 Demo Video

[Link TBD]

## 🏷️ Submission

Final commit tagged: `v1.0-submission`
