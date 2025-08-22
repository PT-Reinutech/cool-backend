# device_config_routes.py - WIB TIMEZONE VERSION

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
from models import User
from pydantic import BaseModel
from typing import Dict, Optional
from datetime import datetime, timezone, timedelta
import logging
import httpx
import ssl

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/devices/config", tags=["device-config"])

# WIB Timezone Configuration
WIB_TIMEZONE = timezone(timedelta(hours=7))  # UTC+7 for WIB

def get_current_timestamp():
    """
    Get current timestamp in WIB timezone
    Returns datetime object with WIB timezone
    """
    return datetime.now(WIB_TIMEZONE)

def get_current_timestamp_iso():
    """
    Get current timestamp in WIB timezone as ISO string
    """
    return get_current_timestamp().isoformat()

def get_current_timestamp_ns():
    """
    Get current timestamp in nanoseconds for InfluxDB (but in WIB)
    Note: InfluxDB stores in UTC internally, but we're providing WIB time
    """
    wib_time = get_current_timestamp()
    # Convert to nanoseconds since epoch
    return int(wib_time.timestamp() * 1000000000)

def get_system_timezone_timestamp():
    """
    Alternative: Get timestamp using system timezone (Ubuntu default)
    This will use whatever timezone is configured in Ubuntu system
    """
    return datetime.now()

def get_system_timezone_timestamp_iso():
    """
    Get system timezone timestamp as ISO string
    """
    return get_system_timezone_timestamp().isoformat()

# Temporary auth dependency
async def get_current_user_temp(db: Session = Depends(get_db)):
    """Temporary auth - replace with actual auth system"""
    from models import User
    user = db.query(User).first()
    if not user:
        raise HTTPException(status_code=401, detail="No user found")
    return user

# Request/Response Models
class ConfigSaveRequest(BaseModel):
    device_id: str
    parameters: Dict[str, float]

class ConfigSaveResponse(BaseModel):
    success: bool
    message: str
    device_id: str
    timestamp: str

class ConfigLoadResponse(BaseModel):
    success: bool
    device_id: str
    parameters: Dict[str, float]
    timestamp: Optional[str] = None

# FIXED: SSL-aware InfluxDB Configuration Service with WIB timezone
class InfluxConfigService:
    """
    SSL-aware service untuk save/load device configuration ke InfluxDB
    Using WIB timezone for all timestamps
    """
    
    @staticmethod
    def _create_ssl_context():
        """
        Create SSL context that handles self-signed certificates
        """
        # Create SSL context that doesn't verify certificates (for self-signed certs)
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        return ssl_context
    
    @staticmethod
    async def save_config_to_influx(device_id: str, parameters: Dict[str, float]) -> bool:
        """
        Save configuration parameters to InfluxDB with SSL handling
        Using WIB timezone for timestamps
        """
        try:
            from influx_config import InfluxConfig
            
            config = InfluxConfig()
            
            # FIXED: Validate configuration first
            config_issues = config.validate_config()
            if config_issues:
                logger.error(f"InfluxDB config issues: {config_issues}")
                raise Exception(f"InfluxDB configuration error: {', '.join(config_issues)}")
            
            # FIXED: Check if InfluxDB is enabled
            if not config.is_enabled():
                logger.warning("InfluxDB validation is disabled, skipping save")
                return True  # Return success if disabled
            
            # UPDATED: Prepare timestamp in WIB
            wib_timestamp = get_current_timestamp()
            timestamp_ns = get_current_timestamp_ns()
            
            logger.info(f"Using WIB timestamp: {wib_timestamp.isoformat()} (ns: {timestamp_ns})")
            
            # Create line protocol entries
            line_protocol_entries = []
            for param_code, param_value in parameters.items():
                # Validate parameter code
                param_code_clean = param_code.lower().strip()
                if not param_code_clean.startswith('f') or len(param_code_clean) != 3:
                    logger.warning(f"Skipping invalid parameter: {param_code}")
                    continue
                
                # Proper line protocol format
                line_entry = f"config_data,{config.DEVICE_ID_TAG}={device_id} {param_code_clean}={param_value} {timestamp_ns}"
                line_protocol_entries.append(line_entry)
            
            if not line_protocol_entries:
                raise Exception("No valid parameters to save")
            
            # Join all entries
            line_protocol = "\n".join(line_protocol_entries)
            
            logger.info(f"Saving config to InfluxDB for device {device_id}: {len(line_protocol_entries)} parameters at WIB time {wib_timestamp.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            logger.debug(f"Line protocol data: {line_protocol}")
            
            # FIXED: Create HTTP client with SSL handling
            ssl_context = InfluxConfigService._create_ssl_context()
            timeout = httpx.Timeout(config.REQUEST_TIMEOUT_SECONDS, connect=5.0)
            
            async with httpx.AsyncClient(timeout=timeout, verify=ssl_context) as client:
                # Headers and parameters
                headers = {
                    "Authorization": config.TOKEN,
                    "Content-Type": "text/plain; charset=utf-8",
                    "Accept": "application/json"
                }
                
                params = {
                    "org": config.ORG,
                    "bucket": config.BUCKET,
                    "precision": "ns"
                }
                
                logger.debug(f"InfluxDB write URL: {config.HOST}/api/v2/write")
                logger.debug(f"InfluxDB params: {params}")
                
                response = await client.post(
                    f"{config.HOST}/api/v2/write",
                    headers=headers,
                    params=params,
                    content=line_protocol.encode('utf-8')
                )
                
                # Enhanced response handling
                if response.status_code == 204:
                    logger.info(f"✅ Successfully saved configuration to InfluxDB for device {device_id} at WIB: {wib_timestamp.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                    return True
                
                elif response.status_code == 401:
                    logger.error("❌ InfluxDB authentication failed")
                    raise Exception("InfluxDB authentication failed. Check token configuration.")
                
                elif response.status_code == 404:
                    logger.error(f"❌ InfluxDB bucket '{config.BUCKET}' not found")
                    raise Exception(f"InfluxDB bucket '{config.BUCKET}' not found. Check bucket configuration.")
                
                elif response.status_code == 400:
                    error_text = response.text
                    logger.error(f"❌ InfluxDB bad request: {error_text}")
                    raise Exception(f"InfluxDB bad request: {error_text}")
                
                else:
                    logger.error(f"❌ InfluxDB write failed: {response.status_code} - {response.text}")
                    raise Exception(f"InfluxDB write failed with status {response.status_code}: {response.text}")
                    
        except httpx.TimeoutException as e:
            logger.error(f"❌ InfluxDB timeout error: {str(e)}")
            raise Exception("InfluxDB connection timeout. Please try again.")
            
        except httpx.ConnectError as e:
            logger.error(f"❌ InfluxDB connection error: {str(e)}")
            raise Exception("Cannot connect to InfluxDB. Check network configuration.")
            
        except Exception as e:
            logger.error(f"❌ Error saving config to InfluxDB: {str(e)}")
            # Re-raise the exception to be handled by the endpoint
            raise e
    
    @staticmethod
    async def load_config_from_influx(device_id: str) -> Optional[Dict[str, float]]:
        """
        Load latest configuration parameters from InfluxDB with SSL handling
        """
        try:
            from influx_config import InfluxConfig
            
            config = InfluxConfig()
            
            # Check if InfluxDB is enabled
            if not config.is_enabled():
                logger.warning("InfluxDB validation is disabled, returning empty config")
                return {}
            
            # Validate configuration
            config_issues = config.validate_config()
            if config_issues:
                logger.error(f"InfluxDB config issues: {config_issues}")
                return {}
            
            # Enhanced Flux query
            flux_query = f'''
from(bucket: "{config.BUCKET}")
  |> range(start: -30d)
  |> filter(fn: (r) => r["_measurement"] == "config_data")
  |> filter(fn: (r) => r["{config.DEVICE_ID_TAG}"] == "{device_id}")
  |> group(columns: ["_field"])
  |> sort(columns: ["_time"], desc: true)
  |> first()
  |> yield(name: "latest_config")
'''
            
            current_wib = get_current_timestamp()
            logger.info(f"Loading config from InfluxDB for device {device_id} at WIB: {current_wib.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            logger.debug(f"Flux query: {flux_query}")
            
            # FIXED: Create HTTP client with SSL handling
            ssl_context = InfluxConfigService._create_ssl_context()
            timeout = httpx.Timeout(config.REQUEST_TIMEOUT_SECONDS, connect=5.0)
            
            async with httpx.AsyncClient(timeout=timeout, verify=ssl_context) as client:
                headers = config.get_headers()
                params = {"org": config.ORG}
                
                response = await client.post(
                    f"{config.HOST}/api/v2/query",
                    headers=headers,
                    params=params,
                    content=flux_query.encode('utf-8')
                )
                
                if response.status_code == 200:
                    result_data = response.text
                    logger.debug(f"InfluxDB response: {result_data[:500]}...")  # First 500 chars
                    
                    # Enhanced CSV parsing
                    parameters = {}
                    
                    if result_data and result_data.strip():
                        lines = result_data.strip().split('\n')
                        
                        # Skip header lines and empty lines
                        data_lines = [line for line in lines if line and not line.startswith('#') and ',' in line]
                        
                        if data_lines:
                            # Process data lines
                            for line in data_lines:
                                try:
                                    parts = line.split(',')
                                    if len(parts) >= 6:  # Expected CSV format
                                        field_name = parts[5].strip('"')  # _field column
                                        field_value = float(parts[6].strip('"'))  # _value column
                                        
                                        if field_name.startswith('f') and len(field_name) == 3:
                                            parameters[field_name] = field_value
                                            
                                except (ValueError, IndexError) as parse_error:
                                    logger.warning(f"Failed to parse line: {line}, error: {parse_error}")
                                    continue
                    
                    if parameters:
                        logger.info(f"✅ Loaded {len(parameters)} parameters for device {device_id} at WIB: {current_wib.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                        return parameters
                    else:
                        logger.info(f"No configuration found for device {device_id}")
                        return {}
                        
                elif response.status_code == 401:
                    logger.error("❌ InfluxDB authentication failed")
                    return {}
                    
                elif response.status_code == 404:
                    logger.error(f"❌ InfluxDB bucket '{config.BUCKET}' not found")
                    return {}
                    
                else:
                    logger.error(f"❌ InfluxDB query failed: {response.status_code} - {response.text}")
                    return {}
                    
        except httpx.TimeoutException:
            logger.error(f"❌ InfluxDB timeout for device {device_id}")
            return {}
            
        except Exception as e:
            logger.error(f"❌ Error loading config from InfluxDB: {str(e)}")
            return {}

@router.post("/save", response_model=ConfigSaveResponse)
async def save_device_config(
    request: ConfigSaveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_temp)
):
    """
    Save device configuration parameters to InfluxDB
    Using WIB timezone for timestamps
    """
    try:
        device_id = request.device_id.strip()
        parameters = request.parameters
        
        current_wib = get_current_timestamp()
        logger.info(f"User {current_user.username} saving config for device {device_id} at WIB: {current_wib.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        logger.debug(f"Parameters to save: {parameters}")
        
        # Enhanced parameter validation
        valid_params = {}
        for param_code, param_value in parameters.items():
            param_code_clean = param_code.lower().strip()
            
            # Validate parameter format (f01-f12)
            if param_code_clean in ['f01', 'f02', 'f03', 'f04', 'f05', 'f06', 'f07', 'f08', 'f09', 'f10', 'f11', 'f12']:
                try:
                    valid_params[param_code_clean] = float(param_value)
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid parameter value for {param_code}: {param_value}, error: {e}")
                    continue
            else:
                logger.warning(f"Invalid parameter code: {param_code}")
        
        if not valid_params:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid configuration parameters provided. Expected F01-F12 parameters."
            )
        
        logger.info(f"Validated {len(valid_params)} parameters: {list(valid_params.keys())}")
        
        # Save to InfluxDB with proper error handling
        try:
            success = await InfluxConfigService.save_config_to_influx(device_id, valid_params)
            
            if success:
                logger.info(f"✅ Configuration saved successfully for device {device_id} at WIB: {current_wib.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                return ConfigSaveResponse(
                    success=True,
                    message=f"Configuration saved successfully for device {device_id}",
                    device_id=device_id,
                    timestamp=get_current_timestamp_iso()  # WIB timestamp
                )
            else:
                raise Exception("InfluxDB save operation returned False")
                
        except Exception as influx_error:
            logger.error(f"❌ InfluxDB save error: {str(influx_error)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to save configuration to InfluxDB: {str(influx_error)}"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected error saving device config: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error saving configuration: {str(e)}"
        )

@router.get("/load/{device_id}", response_model=ConfigLoadResponse)
async def load_device_config(
    device_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_temp)
):
    """
    Load device configuration parameters from InfluxDB
    Using WIB timezone for timestamps
    """
    try:
        device_id = device_id.strip()
        
        current_wib = get_current_timestamp()
        logger.info(f"User {current_user.username} loading config for device {device_id} at WIB: {current_wib.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        
        # Load from InfluxDB
        parameters = await InfluxConfigService.load_config_from_influx(device_id)
        
        if parameters:
            logger.info(f"✅ Configuration loaded successfully for device {device_id}: {len(parameters)} parameters at WIB: {current_wib.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            return ConfigLoadResponse(
                success=True,
                device_id=device_id,
                parameters=parameters,
                timestamp=get_current_timestamp_iso()  # WIB timestamp
            )
        else:
            logger.info(f"No configuration found for device {device_id}, returning defaults")
            return ConfigLoadResponse(
                success=True,
                device_id=device_id,
                parameters={},  # Empty dict to indicate no config found
                timestamp=None
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error loading device config: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error loading configuration: {str(e)}"
        )

# Enhanced health check endpoint with SSL testing and WIB timezone
@router.get("/health")
async def config_health_check():
    """Health check endpoint for configuration service with SSL testing and WIB timezone"""
    try:
        from influx_config import InfluxConfig
        config = InfluxConfig()
        
        current_wib = get_current_timestamp()
        current_system = get_system_timezone_timestamp()
        
        # Validate configuration
        issues = config.validate_config()
        
        # Test InfluxDB connectivity if enabled
        connectivity_status = "disabled"
        influx_error = None
        ssl_status = "unknown"
        
        if config.is_enabled():
            try:
                # Test with SSL context
                ssl_context = InfluxConfigService._create_ssl_context()
                timeout = httpx.Timeout(5.0, connect=2.0)
                
                async with httpx.AsyncClient(timeout=timeout, verify=ssl_context) as client:
                    response = await client.get(
                        f"{config.HOST}/api/v2/health",
                        headers={"Authorization": config.TOKEN}
                    )
                    
                    if response.status_code == 200:
                        connectivity_status = "healthy"
                        ssl_status = "bypassed"
                    else:
                        connectivity_status = f"unhealthy (HTTP {response.status_code})"
                        ssl_status = "bypassed"
                        
            except Exception as e:
                connectivity_status = "error"
                influx_error = str(e)
                ssl_status = "error"
        
        health_status = {
            "status": "healthy" if not issues and connectivity_status in ["healthy", "disabled"] else "warning",
            "service": "device-configuration",
            "influx_enabled": config.is_enabled(),
            "influx_connectivity": connectivity_status,
            "ssl_status": ssl_status,
            "config_issues": issues,
            "timezone_info": {
                "wib_time": current_wib.strftime('%Y-%m-%d %H:%M:%S %Z'),
                "wib_iso": current_wib.isoformat(),
                "system_time": current_system.strftime('%Y-%m-%d %H:%M:%S'),
                "system_iso": current_system.isoformat(),
                "timezone": "WIB (UTC+7)"
            },
            "timestamp": get_current_timestamp_iso()  # WIB timestamp
        }
        
        if influx_error:
            health_status["influx_error"] = influx_error
        
        return health_status
        
    except Exception as e:
        logger.error(f"❌ Health check failed: {str(e)}")
        return {
            "status": "unhealthy",
            "service": "device-configuration",
            "error": str(e),
            "timestamp": get_current_timestamp_iso()  # WIB timestamp
        }

# Debug endpoint with SSL testing and WIB timezone
@router.get("/debug/{device_id}")
async def debug_device_config(device_id: str):
    """Debug endpoint untuk check device configuration di InfluxDB with SSL info and WIB timezone"""
    try:
        from influx_config import InfluxConfig
        config = InfluxConfig()
        
        current_wib = get_current_timestamp()
        current_system = get_system_timezone_timestamp()
        
        if not config.is_enabled():
            return {
                "device_id": device_id,
                "status": "InfluxDB validation disabled",
                "timezone_info": {
                    "wib_time": current_wib.strftime('%Y-%m-%d %H:%M:%S %Z'),
                    "wib_iso": current_wib.isoformat(),
                    "system_time": current_system.strftime('%Y-%m-%d %H:%M:%S'),
                    "system_iso": current_system.isoformat(),
                    "timezone": "WIB (UTC+7)"
                },
                "timestamp": get_current_timestamp_iso()
            }
        
        # Validate config
        issues = config.validate_config()
        if issues:
            return {
                "device_id": device_id,
                "status": "configuration_error",
                "issues": issues,
                "timezone_info": {
                    "wib_time": current_wib.strftime('%Y-%m-%d %H:%M:%S %Z'),
                    "wib_iso": current_wib.isoformat(),
                    "system_time": current_system.strftime('%Y-%m-%d %H:%M:%S'),
                    "system_iso": current_system.isoformat(),
                    "timezone": "WIB (UTC+7)"
                },
                "timestamp": get_current_timestamp_iso()
            }
        
        # Test SSL connection
        ssl_context = InfluxConfigService._create_ssl_context()
        timeout = httpx.Timeout(10.0, connect=5.0)
        
        # Query config data for device
        flux_query = f'''
from(bucket: "{config.BUCKET}")
  |> range(start: -7d)
  |> filter(fn: (r) => r["_measurement"] == "config_data")
  |> filter(fn: (r) => r["{config.DEVICE_ID_TAG}"] == "{device_id}")
  |> sort(columns: ["_time"], desc: true)
  |> limit(n: 50)
'''
        
        async with httpx.AsyncClient(timeout=timeout, verify=ssl_context) as client:
            response = await client.post(
                f"{config.HOST}/api/v2/query",
                headers=config.get_headers(),
                params={"org": config.ORG},
                content=flux_query.encode('utf-8')
            )
            
            return {
                "device_id": device_id,
                "query_status": response.status_code,
                "query_success": response.status_code == 200,
                "raw_response": response.text[:1000] if response.text else "",
                "response_length": len(response.text) if response.text else 0,
                "ssl_handling": "disabled_verification",
                "config_bucket": config.BUCKET,
                "config_org": config.ORG,
                "config_host": config.HOST,
                "timezone_info": {
                    "wib_time": current_wib.strftime('%Y-%m-%d %H:%M:%S %Z'),
                    "wib_iso": current_wib.isoformat(),
                    "system_time": current_system.strftime('%Y-%m-%d %H:%M:%S'),
                    "system_iso": current_system.isoformat(),
                    "timezone": "WIB (UTC+7)"
                },
                "timestamp": get_current_timestamp_iso()  # WIB timestamp
            }
            
    except Exception as e:
        logger.error(f"❌ Debug error: {str(e)}")
        return {
            "device_id": device_id,
            "status": "error",
            "error": str(e),
            "ssl_handling": "error",
            "timestamp": get_current_timestamp_iso()  # WIB timestamp
        }

# Additional endpoint to show timezone comparison
@router.get("/timezone-info")
async def get_timezone_info():
    """
    Endpoint to show current time in different formats for testing
    """
    try:
        wib_time = get_current_timestamp()
        system_time = get_system_timezone_timestamp()
        utc_time = datetime.now(timezone.utc)
        
        return {
            "timezone_comparison": {
                "wib": {
                    "datetime": wib_time.strftime('%Y-%m-%d %H:%M:%S %Z'),
                    "iso": wib_time.isoformat(),
                    "timestamp": wib_time.timestamp(),
                    "timezone": "WIB (UTC+7)"
                },
                "system": {
                    "datetime": system_time.strftime('%Y-%m-%d %H:%M:%S'),
                    "iso": system_time.isoformat(),
                    "timestamp": system_time.timestamp(),
                    "timezone": "System Default (Ubuntu)"
                },
                "utc": {
                    "datetime": utc_time.strftime('%Y-%m-%d %H:%M:%S %Z'),
                    "iso": utc_time.isoformat(),
                    "timestamp": utc_time.timestamp(),
                    "timezone": "UTC+0"
                }
            },
            "recommended": "wib",
            "note": "All application timestamps now use WIB (UTC+7) timezone"
        }
        
    except Exception as e:
        return {
            "error": str(e),
            "timestamp": get_current_timestamp_iso()
        }