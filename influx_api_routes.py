# influx_api_routes.py
# Backend API routes untuk dashboard widget data dari InfluxDB

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import logging
import asyncio
from influxdb_service import InfluxDBService

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/influx", tags=["influx-data"])

# Request/Response Models
class SensorDataRequest(BaseModel):
    chipId: str = Field(..., description="Device chip ID")
    field: str = Field(..., description="Sensor field name (e.g., P1_T, H, Current)")
    measurement: str = Field(default="sensor_data", description="InfluxDB measurement name")
    timeRange: str = Field(default="1h", description="Time range (1h, 6h, 1d, 7d)")
    limit: int = Field(default=100, description="Maximum number of data points")

class LatestValueRequest(BaseModel):
    chipId: str = Field(..., description="Device chip ID")
    field: str = Field(..., description="Sensor field name")
    measurement: str = Field(default="sensor_data", description="InfluxDB measurement name")

class MultiSensorRequest(BaseModel):
    chipId: str = Field(..., description="Device chip ID")
    fields: List[str] = Field(..., description="List of sensor field names")
    measurement: str = Field(default="sensor_data", description="InfluxDB measurement name")
    timeRange: str = Field(default="1h", description="Time range")

class SensorDataPoint(BaseModel):
    time: str
    value: float
    field: str

class SensorDataResponse(BaseModel):
    success: bool
    data: List[SensorDataPoint]
    chipId: str
    field: str
    message: Optional[str] = None

class LatestValueResponse(BaseModel):
    success: bool
    value: Optional[float]
    timestamp: Optional[str]
    chipId: str
    field: str
    unit: Optional[str] = None
    message: Optional[str] = None

class MultiSensorResponse(BaseModel):
    success: bool
    data: Dict[str, List[SensorDataPoint]]
    chipId: str
    message: Optional[str] = None

# Utility functions
def parse_time_range(time_range: str) -> str:
    """Convert time range string to InfluxDB format"""
    range_mapping = {
        "1h": "-1h",
        "6h": "-6h",
        "12h": "-12h",
        "1d": "-1d",
        "7d": "-7d",
        "30d": "-30d"
    }
    return range_mapping.get(time_range, "-1h")

def get_sensor_unit(field: str) -> str:
    """Get unit for sensor field"""
    unit_mapping = {
        # Temperature sensors
        "P1_T": "°C", "P2_T": "°C", "E_T": "°C", "A_T": "°C", "C_T": "°C",
        # Environmental
        "H": "%", "P": "hPa",
        # Electrical
        "Current": "A", "Voltage": "V", "Power": "W", "PF": "", "Energy": "kWh", "Frequency": "Hz",
        # Digital I/O
        "compressor_OUT": "", "defrost_OUT": "", "fan_OUT": "", "light_OUT": "", 
        "door_L": "", "alarm_OUT": ""
    }
    return unit_mapping.get(field, "")

async def get_influx_service() -> InfluxDBService:
    """Dependency untuk InfluxDB service"""
    return InfluxDBService()

@router.post("/sensor-data", response_model=SensorDataResponse)
async def get_sensor_data(
    request: SensorDataRequest,
    influx_service: InfluxDBService = Depends(get_influx_service)
):
    """
    Endpoint untuk mendapatkan data sensor dalam rentang waktu tertentu
    Digunakan untuk chart/graph widgets
    """
    try:
        logger.info(f"Fetching sensor data for {request.chipId}, field: {request.field}")
        
        # Validate time range
        time_start = parse_time_range(request.timeRange)
        
        # Build Flux query
        flux_query = f'''
from(bucket: "{influx_service.config.BUCKET}")
  |> range(start: {time_start})
  |> filter(fn: (r) => r["{influx_service.config.DEVICE_ID_TAG}"] == "{request.chipId}")
  |> filter(fn: (r) => r["_measurement"] == "{request.measurement}")
  |> filter(fn: (r) => r["_field"] == "{request.field}")
  |> sort(columns: ["_time"])
  |> limit(n: {request.limit})
'''
        
        logger.debug(f"InfluxDB query: {flux_query}")
        
        # Execute query
        result_data = await influx_service._execute_query(flux_query)
        
        if not result_data:
            return SensorDataResponse(
                success=False,
                data=[],
                chipId=request.chipId,
                field=request.field,
                message=f"No data found for device {request.chipId} field {request.field}"
            )
        
        # Parse CSV response
        data_points = []
        lines = result_data.strip().split('\n')
        
        # Find header
        header_idx = -1
        for i, line in enumerate(lines):
            if line.startswith('_result') or line.startswith(',_result'):
                header_idx = i
                break
        
        if header_idx >= 0:
            header = lines[header_idx].split(',')
            time_idx = header.index('_time') if '_time' in header else -1
            value_idx = header.index('_value') if '_value' in header else -1
            
            if time_idx >= 0 and value_idx >= 0:
                for line in lines[header_idx + 1:]:
                    if line.strip() and not line.startswith('#'):
                        parts = line.split(',')
                        if len(parts) > max(time_idx, value_idx):
                            try:
                                time_str = parts[time_idx]
                                value_str = parts[value_idx]
                                
                                if time_str and value_str:
                                    data_points.append(SensorDataPoint(
                                        time=time_str,
                                        value=float(value_str),
                                        field=request.field
                                    ))
                            except (ValueError, IndexError) as e:
                                logger.warning(f"Error parsing line: {line}, error: {e}")
                                continue
        
        logger.info(f"Found {len(data_points)} data points for {request.chipId}.{request.field}")
        
        return SensorDataResponse(
            success=True,
            data=data_points,
            chipId=request.chipId,
            field=request.field,
            message=f"Found {len(data_points)} data points"
        )
        
    except Exception as e:
        logger.error(f"Error fetching sensor data: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching sensor data: {str(e)}"
        )

@router.post("/latest-value", response_model=LatestValueResponse)
async def get_latest_value(
    request: LatestValueRequest,
    influx_service: InfluxDBService = Depends(get_influx_service)
):
    """
    Endpoint untuk mendapatkan nilai terbaru dari sensor
    Digunakan untuk gauge, sensor card widgets
    """
    try:
        logger.info(f"Fetching latest value for {request.chipId}, field: {request.field}")
        
        # Build Flux query untuk data terbaru
        flux_query = f'''
from(bucket: "{influx_service.config.BUCKET}")
  |> range(start: -24h)
  |> filter(fn: (r) => r["{influx_service.config.DEVICE_ID_TAG}"] == "{request.chipId}")
  |> filter(fn: (r) => r["_measurement"] == "{request.measurement}")
  |> filter(fn: (r) => r["_field"] == "{request.field}")
  |> sort(columns: ["_time"], desc: true)
  |> limit(n: 1)
'''
        
        logger.debug(f"InfluxDB query: {flux_query}")
        
        # Execute query
        result_data = await influx_service._execute_query(flux_query)
        
        if not result_data:
            return LatestValueResponse(
                success=False,
                value=None,
                timestamp=None,
                chipId=request.chipId,
                field=request.field,
                unit=get_sensor_unit(request.field),
                message=f"No recent data found for device {request.chipId} field {request.field}"
            )
        
        # Parse latest value
        lines = result_data.strip().split('\n')
        
        # Find header and data
        header_idx = -1
        for i, line in enumerate(lines):
            if line.startswith('_result') or line.startswith(',_result'):
                header_idx = i
                break
        
        if header_idx >= 0 and len(lines) > header_idx + 1:
            header = lines[header_idx].split(',')
            time_idx = header.index('_time') if '_time' in header else -1
            value_idx = header.index('_value') if '_value' in header else -1
            
            data_line = lines[header_idx + 1]
            if data_line.strip() and not data_line.startswith('#'):
                parts = data_line.split(',')
                if len(parts) > max(time_idx, value_idx) and time_idx >= 0 and value_idx >= 0:
                    try:
                        time_str = parts[time_idx]
                        value_str = parts[value_idx]
                        
                        if time_str and value_str:
                            return LatestValueResponse(
                                success=True,
                                value=float(value_str),
                                timestamp=time_str,
                                chipId=request.chipId,
                                field=request.field,
                                unit=get_sensor_unit(request.field),
                                message="Latest value retrieved successfully"
                            )
                    except ValueError as e:
                        logger.warning(f"Error parsing value: {value_str}, error: {e}")
        
        return LatestValueResponse(
            success=False,
            value=None,
            timestamp=None,
            chipId=request.chipId,
            field=request.field,
            unit=get_sensor_unit(request.field),
            message="Unable to parse latest value"
        )
        
    except Exception as e:
        logger.error(f"Error fetching latest value: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching latest value: {str(e)}"
        )

@router.post("/multi-sensor-data", response_model=MultiSensorResponse)
async def get_multi_sensor_data(
    request: MultiSensorRequest,
    influx_service: InfluxDBService = Depends(get_influx_service)
):
    """
    Endpoint untuk mendapatkan data multiple sensors sekaligus
    Digunakan untuk electrical, environmental, digital I/O widgets
    """
    try:
        logger.info(f"Fetching multi-sensor data for {request.chipId}, fields: {request.fields}")
        
        time_start = parse_time_range(request.timeRange)
        
        # Build field filter
        field_filter = " or ".join([f'r["_field"] == "{field}"' for field in request.fields])
        
        # Build Flux query
        flux_query = f'''
from(bucket: "{influx_service.config.BUCKET}")
  |> range(start: {time_start})
  |> filter(fn: (r) => r["{influx_service.config.DEVICE_ID_TAG}"] == "{request.chipId}")
  |> filter(fn: (r) => r["_measurement"] == "{request.measurement}")
  |> filter(fn: (r) => {field_filter})
  |> sort(columns: ["_time"])
  |> limit(n: 1000)
'''
        
        logger.debug(f"InfluxDB multi-sensor query: {flux_query}")
        
        # Execute query
        result_data = await influx_service._execute_query(flux_query)
        
        if not result_data:
            return MultiSensorResponse(
                success=False,
                data={field: [] for field in request.fields},
                chipId=request.chipId,
                message=f"No data found for device {request.chipId}"
            )
        
        # Parse CSV response dan group by field
        field_data = {field: [] for field in request.fields}
        lines = result_data.strip().split('\n')
        
        # Find header
        header_idx = -1
        for i, line in enumerate(lines):
            if line.startswith('_result') or line.startswith(',_result'):
                header_idx = i
                break
        
        if header_idx >= 0:
            header = lines[header_idx].split(',')
            time_idx = header.index('_time') if '_time' in header else -1
            value_idx = header.index('_value') if '_value' in header else -1
            field_idx = header.index('_field') if '_field' in header else -1
            
            if time_idx >= 0 and value_idx >= 0 and field_idx >= 0:
                for line in lines[header_idx + 1:]:
                    if line.strip() and not line.startswith('#'):
                        parts = line.split(',')
                        if len(parts) > max(time_idx, value_idx, field_idx):
                            try:
                                time_str = parts[time_idx]
                                value_str = parts[value_idx]
                                field_str = parts[field_idx]
                                
                                if time_str and value_str and field_str in request.fields:
                                    field_data[field_str].append(SensorDataPoint(
                                        time=time_str,
                                        value=float(value_str),
                                        field=field_str
                                    ))
                            except (ValueError, IndexError) as e:
                                logger.warning(f"Error parsing line: {line}, error: {e}")
                                continue
        
        total_points = sum(len(data) for data in field_data.values())
        logger.info(f"Found {total_points} total data points for {request.chipId} across {len(request.fields)} fields")
        
        return MultiSensorResponse(
            success=True,
            data=field_data,
            chipId=request.chipId,
            message=f"Found data for {len([f for f in field_data if field_data[f]])} out of {len(request.fields)} fields"
        )
        
    except Exception as e:
        logger.error(f"Error fetching multi-sensor data: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching multi-sensor data: {str(e)}"
        )

# Helper endpoints untuk specific widget types

@router.get("/temperature-data/{chip_id}")
async def get_temperature_data(
    chip_id: str,
    time_range: str = "1h",
    influx_service: InfluxDBService = Depends(get_influx_service)
):
    """Helper endpoint untuk temperature widgets"""
    request = MultiSensorRequest(
        chipId=chip_id,
        fields=["P1_T", "P2_T", "E_T", "A_T", "C_T"],
        measurement="sensor_data",
        timeRange=time_range
    )
    return await get_multi_sensor_data(request, influx_service)

@router.get("/electrical-data/{chip_id}")
async def get_electrical_data(
    chip_id: str,
    time_range: str = "1h",
    influx_service: InfluxDBService = Depends(get_influx_service)
):
    """Helper endpoint untuk electrical widget"""
    request = MultiSensorRequest(
        chipId=chip_id,
        fields=["Current", "Voltage", "Power", "PF", "Energy", "Frequency"],
        measurement="sensor_data",
        timeRange=time_range
    )
    return await get_multi_sensor_data(request, influx_service)

@router.get("/environmental-data/{chip_id}")
async def get_environmental_data(
    chip_id: str,
    time_range: str = "1h",
    influx_service: InfluxDBService = Depends(get_influx_service)
):
    """Helper endpoint untuk environmental widget"""
    request = MultiSensorRequest(
        chipId=chip_id,
        fields=["H", "P"],
        measurement="sensor_data",
        timeRange=time_range
    )
    return await get_multi_sensor_data(request, influx_service)

@router.get("/digital-io-data/{chip_id}")
async def get_digital_io_data(
    chip_id: str,
    time_range: str = "1h",
    influx_service: InfluxDBService = Depends(get_influx_service)
):
    """Helper endpoint untuk digital I/O widget"""
    request = MultiSensorRequest(
        chipId=chip_id,
        fields=["compressor_OUT", "defrost_OUT", "fan_OUT", "light_OUT", "door_L", "alarm_OUT"],
        measurement="sensor_data",
        timeRange=time_range
    )
    return await get_multi_sensor_data(request, influx_service)

@router.get("/device-status/{chip_id}")
async def get_device_status(
    chip_id: str,
    influx_service: InfluxDBService = Depends(get_influx_service)
):
    """
    Check device connectivity dan status
    """
    try:
        # Get latest heartbeat data
        request = LatestValueRequest(
            chipId=chip_id,
            field="P1_T",  # Use P1_T as heartbeat
            measurement="sensor_data"
        )
        
        latest_response = await get_latest_value(request, influx_service)
        
        if latest_response.success and latest_response.timestamp:
            last_seen = datetime.fromisoformat(latest_response.timestamp.replace('Z', '+00:00'))
            now = datetime.now(last_seen.tzinfo)
            minutes_offline = (now - last_seen).total_seconds() / 60
            
            return {
                "success": True,
                "chipId": chip_id,
                "isOnline": minutes_offline < 5,  # Consider offline if no data for 5+ minutes
                "lastSeen": latest_response.timestamp,
                "minutesOffline": int(minutes_offline),
                "status": "online" if minutes_offline < 5 else "offline"
            }
        
        return {
            "success": False,
            "chipId": chip_id,
            "isOnline": False,
            "lastSeen": None,
            "minutesOffline": None,
            "status": "unknown",
            "message": "No recent data found"
        }
        
    except Exception as e:
        logger.error(f"Error checking device status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error checking device status: {str(e)}"
        )

@router.get("/system-overview")
async def get_system_overview(
    influx_service: InfluxDBService = Depends(get_influx_service)
):
    """
    Get system-wide overview data untuk system overview widget
    """
    try:
        # This would typically get data from multiple devices
        # For now, return mock data structure
        return {
            "success": True,
            "totalDevices": 3,
            "onlineDevices": 3,
            "totalAlarms": 2,
            "activeAlarms": 2,
            "averageTemperature": -18.2,
            "systemHealth": 95,
            "powerUsage": 7.8,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error fetching system overview: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching system overview: {str(e)}"
        )

# Add utility method to InfluxDBService class
async def _execute_query(self, flux_query: str) -> str:
    """Execute Flux query dan return raw CSV result"""
    import httpx
    
    try:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.config.HOST}/api/v2/query",
                headers=self.config.get_headers(),
                params={"org": self.config.ORG},
                data=flux_query
            )
            
            if response.status_code == 200:
                return response.text
            else:
                logger.error(f"InfluxDB query failed: {response.status_code} - {response.text}")
                return ""
                
    except Exception as e:
        logger.error(f"Error executing InfluxDB query: {str(e)}")
        return ""

# Monkey patch the method to InfluxDBService
InfluxDBService._execute_query = _execute_query