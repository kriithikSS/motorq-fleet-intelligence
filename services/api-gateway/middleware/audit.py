from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
import time
import json
import uuid
from datetime import datetime, timezone

try:
    from confluent_kafka import Producer
    HAS_KAFKA = True
except ImportError:
    HAS_KAFKA = False

import os

# Configure Kafka Producer for Audit Logs
KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
AUDIT_TOPIC = "audit-log"

producer = None
if HAS_KAFKA:
    producer = Producer({
        "bootstrap.servers": KAFKA_BOOTSTRAP,
        "client.id": "api-gateway-audit",
        "acks": "all" # Wait for all in-sync replicas to acknowledge (CP tradeoff)
    })

class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Extract basic info
        method = request.method
        url = str(request.url)
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")
        
        # We can attempt to extract the user from the JWT if present,
        # but since this runs before the endpoint dependencies, we might just look at the header.
        auth_header = request.headers.get("authorization")
        user_sub = "anonymous"
        tenant_id = "unknown"
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            try:
                # Basic decode without verification just to extract fields for audit log
                import jwt
                unverified_payload = jwt.decode(token, options={"verify_signature": False})
                user_sub = unverified_payload.get("sub", "anonymous")
                tenant_id = unverified_payload.get("tenant_id", "unknown")
            except Exception:
                pass
        
        # Process request
        response = await call_next(request)
        
        process_time = time.time() - start_time
        status_code = response.status_code
        
        # Skip audit for health/metrics to avoid spam
        if request.url.path not in ["/health", "/metrics", "/api/docs", "/api/openapi.json"]:
            audit_event = {
                "event_id": str(uuid.uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "user_sub": user_sub,
                "tenant_id": tenant_id,
                "method": method,
                "url": url,
                "status_code": status_code,
                "client_ip": client_ip,
                "user_agent": user_agent,
                "process_time_ms": round(process_time * 1000, 2)
            }
            
            if producer:
                producer.produce(
                    AUDIT_TOPIC,
                    key=tenant_id.encode(),
                    value=json.dumps(audit_event).encode()
                )
                producer.poll(0)
                
        return response
