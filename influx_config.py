# influx_config.py - InfluxDB Configuration
import os
from dotenv import load_dotenv

load_dotenv()

class InfluxConfig:
    """
    Configuration class untuk InfluxDB settings
    """
    
    # InfluxDB Connection Settings
    HOST = os.getenv("INFLUX_HOST", "https://influx.reinutechiot.com")
    ORG = os.getenv("INFLUX_ORG", "")
    BUCKET = os.getenv("INFLUX_BUCKET", "")  # Updated bucket name
    TOKEN = os.getenv("INFLUX_TOKEN", "")
    
    # Data Structure Settings
    DEVICE_ID_TAG = os.getenv("INFLUX_DEVICE_ID_TAG", "chipid")  # Tag name untuk device ID
    
    # Validation Settings
    DEFAULT_TIME_WINDOW_MINUTES = int(os.getenv("INFLUX_DEFAULT_TIME_WINDOW", "60"))
    EXTENDED_TIME_WINDOW_MINUTES = int(os.getenv("INFLUX_EXTENDED_TIME_WINDOW", "1440"))  # 24 hours
    REQUEST_TIMEOUT_SECONDS = float(os.getenv("INFLUX_TIMEOUT", "10.0"))
    
    # Feature Flags
    ENABLE_INFLUX_VALIDATION = os.getenv("ENABLE_INFLUX_VALIDATION", "true").lower() == "true"
    STRICT_VALIDATION = os.getenv("INFLUX_STRICT_VALIDATION", "true").lower() == "true"
    
    @classmethod
    def get_headers(cls):
        """Get HTTP headers untuk InfluxDB requests"""
        return {
            "Authorization": cls.TOKEN,
            "Content-Type": "application/json",
            "Accept": "application/csv"
        }
    
    @classmethod
    def is_enabled(cls):
        """Check if InfluxDB validation is enabled"""
        return cls.ENABLE_INFLUX_VALIDATION
    
    @classmethod
    def validate_config(cls):
        """Validate configuration settings"""
        issues = []
        
        if not cls.HOST.startswith(('http://', 'https://')):
            issues.append("INFLUX_HOST must start with http:// or https://")
        
        if not cls.TOKEN or not cls.TOKEN.startswith('Token '):
            issues.append("INFLUX_TOKEN must start with 'Token ' prefix")
        
        if not cls.ORG:
            issues.append("INFLUX_ORG cannot be empty")
        
        if not cls.BUCKET:
            issues.append("INFLUX_BUCKET cannot be empty")
        
        return issues