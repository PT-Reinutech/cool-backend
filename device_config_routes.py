# device_config_routes.py - Routes untuk save/load configuration ke InfluxDB
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
from models import User
from pydantic import BaseModel
from typing import Dict, Optional
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/devices/config", tags=["device-config"])

# Temporary auth dependency - ganti dengan yang sesuai
async def get_current_user_temp(db: Session = Depends(get_db)):
    """Temporary auth - replace with actual auth system"""
    from models import User
    user = db.query(User).first()
    if not user:
        raise HTTPException(status_code=401, detail="No user found")
    return user

# Pydantic models untuk configuration
class ConfigSaveRequest(BaseModel):
    device_id: str
    parameters: Dict[str, float]  # f01: -18.0, f02: 2.0, etc.

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

# InfluxDB Configuration Service
class InfluxConfigService:
    """
    Service untuk save/load device configuration ke InfluxDB
    """
    
    @staticmethod
    async def save_config_to_influx(device_id: str, parameters: Dict[str, float]) -> bool:
        """
        Save configuration parameters to InfluxDB
        Format: chipid=device_id, _measurement=config_data, _field=f01/f02/etc, _value=parameter_value
        """
        try:
            from influx_config import InfluxConfig
            import httpx
            
            config = InfluxConfig()
            
            # Prepare InfluxDB line protocol data
            timestamp = datetime.utcnow()
            
            # Create line protocol entries for each parameter
            line_protocol_entries = []
            for param_code, param_value in parameters.items():
                # Format: measurement,tag1=value1,tag2=value2 field1=value1,field2=value2 timestamp
                line_entry = f"config_data,{config.DEVICE_ID_TAG}={device_id} {param_code}={param_value} {int(timestamp.timestamp() * 1000000000)}"
                line_protocol_entries.append(line_entry)
            
            # Join all entries
            line_protocol = "\n".join(line_protocol_entries)
            
            logger.info(f"Saving config to InfluxDB for device {device_id}: {len(parameters)} parameters")
            logger.debug(f"Line protocol: {line_protocol}")
            
            # Send to InfluxDB
            async with httpx.AsyncClient(timeout=config.REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{config.HOST}/api/v2/write",
                    headers={
                        "Authorization": config.TOKEN,
                        "Content-Type": "text/plain"
                    },
                    params={
                        "org": config.ORG,
                        "bucket": config.BUCKET,
                        "precision": "ns"
                    },
                    data=line_protocol
                )
                
                if response.status_code == 204:
                    logger.info(f"Successfully saved configuration to InfluxDB for device {device_id}")
                    return True
                else:
                    logger.error(f"Failed to save to InfluxDB: {response.status_code} - {response.text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error saving config to InfluxDB: {str(e)}")
            return False
    
    @staticmethod
    async def load_config_from_influx(device_id: str) -> Optional[Dict[str, float]]:
        """
        Load latest configuration parameters from InfluxDB
        """
        try:
            from influx_config import InfluxConfig
            import httpx
            
            config = InfluxConfig()
            
            # Flux query to get latest config for device
            flux_query = f'''
from(bucket: "{config.BUCKET}")
  |> range(start: -30d)
  |> filter(fn: (r) => r["_measurement"] == "config_data")
  |> filter(fn: (r) => r["{config.DEVICE_ID_TAG}"] == "{device_id}")
  |> group(columns: ["_field"])
  |> sort(columns: ["_time"], desc: true)
  |> first()
'''
            
            logger.info(f"Loading config from InfluxDB for device {device_id}")
            
            async with httpx.AsyncClient(timeout=config.REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{config.HOST}/api/v2/query",
                    headers=config.get_headers(),
                    params={"org": config.ORG},
                    data=flux_query
                )
                
                if response.status_code == 200:
                    result_data = response.text
                    
                    # Parse CSV response
                    lines = result_data.strip().split('\n')
                    parameters = {}
                    
                    # Find header and parse data
                    header_idx = -1
                    for i, line in enumerate(lines):
                        if line.startswith('_result') or line.startswith(',_result'):
                            header_idx = i
                            break
                    
                    if header_idx >= 0:
                        header = lines[header_idx].split(',')
                        
                        # Find column indices
                        field_idx = value_idx = -1
                        for i, col in enumerate(header):
                            if col == '_field':
                                field_idx = i
                            elif col == '_value':
                                value_idx = i
                        
                        # Parse data rows
                        for line in lines[header_idx + 1:]:
                            if line.strip() and not line.startswith('#'):
                                parts = line.split(',')
                                if len(parts) > max(field_idx, value_idx):
                                    field_name = parts[field_idx]
                                    field_value = parts[value_idx]
                                    
                                    try:
                                        parameters[field_name] = float(field_value)
                                    except (ValueError, IndexError):
                                        continue
                    
                    if parameters:
                        logger.info(f"Loaded {len(parameters)} parameters for device {device_id}")
                        return parameters
                    else:
                        logger.info(f"No configuration found for device {device_id}")
                        return None
                        
                else:
                    logger.error(f"Failed to load from InfluxDB: {response.status_code} - {response.text}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error loading config from InfluxDB: {str(e)}")
            return None

@router.post("/save", response_model=ConfigSaveResponse)
async def save_device_config(
    request: ConfigSaveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_temp)
):
    """
    Save device configuration parameters to InfluxDB
    """
    try:
        device_id = request.device_id.strip()
        parameters = request.parameters
        
        logger.info(f"User {current_user.username} saving config for device {device_id}")
        
        # Validate parameters (F01-F12)
        valid_params = {}
        for param_code, param_value in parameters.items():
            if param_code.lower() in ['f01', 'f02', 'f03', 'f04', 'f05', 'f06', 'f07', 'f08', 'f09', 'f10', 'f11', 'f12']:
                valid_params[param_code.lower()] = float(param_value)
        
        if not valid_params:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid configuration parameters provided (F01-F12)"
            )
        
        # Save to InfluxDB
        success = await InfluxConfigService.save_config_to_influx(device_id, valid_params)
        
        if success:
            logger.info(f"Configuration saved successfully for device {device_id}")
            return ConfigSaveResponse(
                success=True,
                message=f"Configuration saved successfully for device {device_id}",
                device_id=device_id,
                timestamp=datetime.utcnow().isoformat()
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save configuration to InfluxDB"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving device config: {str(e)}")
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
    """
    try:
        device_id = device_id.strip()
        
        logger.info(f"User {current_user.username} loading config for device {device_id}")
        
        # Load from InfluxDB
        parameters = await InfluxConfigService.load_config_from_influx(device_id)
        
        if parameters:
            logger.info(f"Configuration loaded successfully for device {device_id}")
            return ConfigLoadResponse(
                success=True,
                device_id=device_id,
                parameters=parameters,
                timestamp=datetime.utcnow().isoformat()
            )
        else:
            # FIXED: Return success=True but empty parameters instead of 404
            logger.info(f"No configuration found for device {device_id}, returning defaults")
            return ConfigLoadResponse(
                success=True,
                device_id=device_id,
                parameters={},  # Empty dict untuk indicate no config found
                timestamp=None
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading device config: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error loading configuration: {str(e)}"
        )

# Health check endpoint untuk config service
@router.get("/health")
async def config_health_check():
    """Health check endpoint for configuration service"""
    try:
        from influx_config import InfluxConfig
        config = InfluxConfig()
        
        # Validate configuration
        issues = config.validate_config()
        
        return {
            "status": "healthy" if not issues else "warning",
            "service": "device-configuration",
            "influx_enabled": config.is_enabled(),
            "config_issues": issues,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {
            "status": "unhealthy",
            "service": "device-configuration",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

# Debug endpoint
@router.get("/debug/{device_id}")
async def debug_device_config(device_id: str):
    """Debug endpoint untuk check device configuration di InfluxDB"""
    try:
        from influx_config import InfluxConfig
        import httpx
        
        config = InfluxConfig()
        
        # Query semua config data untuk device
        flux_query = f'''
from(bucket: "{config.BUCKET}")
  |> range(start: -7d)
  |> filter(fn: (r) => r["_measurement"] == "config_data")
  |> filter(fn: (r) => r["{config.DEVICE_ID_TAG}"] == "{device_id}")
  |> sort(columns: ["_time"], desc: true)
  |> limit(n: 50)
'''
        
        async with httpx.AsyncClient(timeout=config.REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{config.HOST}/api/v2/query",
                headers=config.get_headers(),
                params={"org": config.ORG},
                data=flux_query
            )
            
            return {
                "device_id": device_id,
                "query_status": response.status_code,
                "raw_response": response.text[:1000],  # First 1000 chars
                "response_length": len(response.text),
                "timestamp": datetime.utcnow().isoformat()
            }
            
    except Exception as e:
        return {
            "device_id": device_id,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }