# audit_logger.py - Advanced audit logging
from sqlalchemy.orm import Session
from models import UserLog
import json

class AuditLogger:
    """
    Advanced audit logging untuk compliance dan security monitoring
    """
    
    def __init__(self, db: Session, redis_client: redis.Redis):
        self.db = db
        self.redis_client = redis_client

    async def log_authentication_event(self, user_id: str, event_type: str, 
                                     client_ip: str, user_agent: str, 
                                     success: bool, details: dict = None):
        """Log authentication events"""
        log_entry = UserLog(
            user_id=user_id,
            action=f"AUTH_{event_type}",
            ip_address=client_ip,
            user_agent=user_agent
        )
        
        # Add additional details
        if details:
            log_entry.details = json.dumps(details)
        
        self.db.add(log_entry)
        self.db.commit()
        
        # Also store in Redis for real-time monitoring
        redis_key = f"auth_event:{datetime.utcnow().timestamp()}"
        event_data = {
            "user_id": user_id,
            "event_type": event_type,
            "client_ip": client_ip,
            "success": success,
            "timestamp": datetime.utcnow().isoformat(),
            "details": details or {}
        }
        
        self.redis_client.setex(redis_key, 3600, json.dumps(event_data))

    async def log_device_interaction(self, user_id: str, product_id: str, 
                                   action: str, client_ip: str, 
                                   parameters: dict = None):
        """Log device interactions untuk IoT audit trail"""
        log_entry = UserLog(
            user_id=user_id,
            product_id=product_id,
            action=f"DEVICE_{action}",
            ip_address=client_ip
        )
        
        if parameters:
            log_entry.details = json.dumps(parameters)
        
        self.db.add(log_entry)
        self.db.commit()

    async def log_configuration_change(self, user_id: str, product_id: str, 
                                     config_type: str, old_values: dict, 
                                     new_values: dict, client_ip: str):
        """Log configuration changes"""
        change_details = {
            "config_type": config_type,
            "old_values": old_values,
            "new_values": new_values,
            "changed_fields": list(set(new_values.keys()) - set(old_values.keys()))
        }
        
        log_entry = UserLog(
            user_id=user_id,
            product_id=product_id,
            action="CONFIG_CHANGE",
            ip_address=client_ip,
            details=json.dumps(change_details)
        )
        
        self.db.add(log_entry)
        self.db.commit()

    async def generate_audit_report(self, start_date: datetime, 
                                  end_date: datetime, 
                                  user_id: str = None) -> dict:
        """Generate audit report untuk compliance"""
        query = self.db.query(UserLog).filter(
            UserLog.timestamp >= start_date,
            UserLog.timestamp <= end_date
        )
        
        if user_id:
            query = query.filter(UserLog.user_id == user_id)
        
        logs = query.all()
        
        # Analyze logs
        report = {
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            },
            "total_events": len(logs),
            "event_types": {},
            "users": {},
            "devices": {},
            "security_events": []
        }
        
        for log in logs:
            # Count by event type
            if log.action not in report["event_types"]:
                report["event_types"][log.action] = 0
            report["event_types"][log.action] += 1
            
            # Count by user
            if log.user_id not in report["users"]:
                report["users"][log.user_id] = 0
            report["users"][log.user_id] += 1
            
            # Count by device
            if log.product_id:
                if log.product_id not in report["devices"]:
                    report["devices"][log.product_id] = 0
                report["devices"][log.product_id] += 1
            
            # Identify security events
            if any(keyword in log.action for keyword in ["FAIL", "BLOCK", "INVALID"]):
                report["security_events"].append({
                    "timestamp": log.timestamp.isoformat(),
                    "user_id": log.user_id,
                    "action": log.action,
                    "ip_address": log.ip_address
                })
        
        return report