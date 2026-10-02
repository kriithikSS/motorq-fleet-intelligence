from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # OWASP Top 10 Mitigations via Headers
        # 1. Prevent Clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        # 2. XSS Protection
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # 3. MIME Sniffing Prevention
        response.headers["X-Content-Type-Options"] = "nosniff"
        # 4. Content Security Policy (Basic)
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; object-src 'none';"
        # 5. Strict-Transport-Security (HSTS)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # 6. Referrer Policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        return response
