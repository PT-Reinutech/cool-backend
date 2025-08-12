# middleware.py - Security middleware tambahan untuk Koronka
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from datetime import datetime, timedelta
import ipaddress
import redis
import json
from typing import Optional

class SecurityMiddleware(BaseHTTPMiddleware):
    """
    Advanced security middleware untuk proteksi sistem Koronka
    """
    
    def __init__(self, app, redis_client: Optional[redis.Redis] = None):
        super().__init__(app)
        self.redis_client = redis_client or redis.Redis(host='localhost', port=6379, db=0)
        
        # Whitelist IP untuk akses internal
        self.allowed_networks = [
            ipaddress.ip_network("192.168.0.0/16"),
            ipaddress.ip_network("192.168.100.0/24"),
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("127.0.0.0/8"),
            ipaddress.ip_network("100.69.240.25/32"),  # IP spesifik yang diizinkan
        ]   
        
        # Rate limiting configuration
        self.rate_limits = {
            "/auth/login": {"requests": 5, "window": 300},      # 5 requests per 5 minutes
            "/auth/register": {"requests": 2, "window": 3600},  # 2 requests per hour
            "default": {"requests": 100, "window": 60}          # 100 requests per minute
        }

    async def dispatch(self, request: Request, call_next):
        start_time = datetime.utcnow()
        client_ip = self.get_client_ip(request)
        
        # 1. IP Whitelist check for sensitive endpoints
        if request.url.path.startswith("/auth/") and not self.is_ip_allowed(client_ip):
            await self.log_security_event(
                event_type="IP_BLOCKED",
                client_ip=client_ip,
                endpoint=request.url.path,
                details=f"IP {client_ip} not in whitelist"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied from this IP address"
            )
        
        # 2. Rate limiting
        if not await self.check_rate_limit(client_ip, request.url.path):
            await self.log_security_event(
                event_type="RATE_LIMIT_EXCEEDED",
                client_ip=client_ip,
                endpoint=request.url.path,
                details="Rate limit exceeded"
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded"
            )
        
        # 3. Request validation
        if not self.validate_request(request):
            await self.log_security_event(
                event_type="INVALID_REQUEST",
                client_ip=client_ip,
                endpoint=request.url.path,
                details="Invalid request format"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid request"
            )
        
        # Process request
        response = await call_next(request)
        
        # 4. Log request
        processing_time = (datetime.utcnow() - start_time).total_seconds()
        await self.log_request(request, response, client_ip, processing_time)
        
        return response

    def get_client_ip(self, request: Request) -> str:
        """Get real client IP considering proxy headers"""
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        return request.client.host

    def is_ip_allowed(self, ip_str: str) -> bool:
        """Check if IP is in allowed networks"""
        try:
            ip = ipaddress.ip_address(ip_str)
            return any(ip in network for network in self.allowed_networks)
        except ValueError:
            return False

    async def check_rate_limit(self, client_ip: str, endpoint: str) -> bool:
        """Check rate limiting using Redis"""
        try:
            # Get rate limit config for endpoint
            limit_config = self.rate_limits.get(endpoint, self.rate_limits["default"])
            max_requests = limit_config["requests"]
            window = limit_config["window"]
            
            # Redis key for this IP and endpoint
            key = f"rate_limit:{client_ip}:{endpoint}"
            
            # Get current count
            current = self.redis_client.get(key)
            if current is None:
                # First request in window
                self.redis_client.setex(key, window, 1)
                return True
            
            current_count = int(current)
            if current_count >= max_requests:
                return False
            
            # Increment counter
            self.redis_client.incr(key)
            return True
            
        except Exception:
            # If Redis fails, allow request (fail open)
            return True

    def validate_request(self, request: Request) -> bool:
        """Basic request validation"""
        # Check Content-Length
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > 1024 * 1024:  # 1MB limit
            return False
        
        # Check User-Agent
        user_agent = request.headers.get("user-agent", "")
        if len(user_agent) > 500:
            return False
        
        # Block common attack patterns
        suspicious_patterns = ["<script", "javascript:", "sql", "union", "select"]
        query_string = str(request.url.query).lower()
        if any(pattern in query_string for pattern in suspicious_patterns):
            return False
        
        return True

    async def log_security_event(self, event_type: str, client_ip: str, 
                                endpoint: str, details: str):
        """Log security events to Redis and potentially alert"""
        try:
            event = {
                "timestamp": datetime.utcnow().isoformat(),
                "event_type": event_type,
                "client_ip": client_ip,
                "endpoint": endpoint,
                "details": details
            }
            
            # Store in Redis with TTL
            key = f"security_event:{datetime.utcnow().timestamp()}"
            self.redis_client.setex(key, 86400, json.dumps(event))  # 24 hour TTL
            
            # For critical events, could trigger alerts here
            if event_type in ["IP_BLOCKED", "RATE_LIMIT_EXCEEDED"]:
                await self.trigger_alert(event)
                
        except Exception as e:
            # Don't fail the request if logging fails
            print(f"Failed to log security event: {e}")

    async def log_request(self, request: Request, response, client_ip: str, 
                         processing_time: float):
        """Log all requests for audit trail"""
        try:
            log_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "client_ip": client_ip,
                "method": request.method,
                "endpoint": str(request.url.path),
                "status_code": response.status_code,
                "processing_time": processing_time,
                "user_agent": request.headers.get("user-agent", ""),
            }
            
            # Store in Redis with shorter TTL for performance logs
            key = f"request_log:{datetime.utcnow().timestamp()}"
            self.redis_client.setex(key, 3600, json.dumps(log_entry))  # 1 hour TTL
            
        except Exception:
            # Silent fail for request logging
            pass

    async def trigger_alert(self, event: dict):
        """Trigger security alerts for critical events"""
        # This could integrate with email, Slack, SMS, etc.
        # For now, just log to console
        print(f"SECURITY ALERT: {event['event_type']} from {event['client_ip']}")
