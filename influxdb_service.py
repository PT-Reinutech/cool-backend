# influxdb_service.py - Updated untuk struktur data yang benar
import httpx
import asyncio
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timedelta
import logging
from influx_config import InfluxConfig

logger = logging.getLogger(__name__)

class InfluxDBService:
    """
    Service untuk validasi device di InfluxDB dan retrieve sensor data
    Berdasarkan struktur: bucket=coolingmonitoring, tag=chipid, measurements=config_data/sensor_data
    """
    
    def __init__(self):
        self.config = InfluxConfig()
        self.timeout = self.config.REQUEST_TIMEOUT_SECONDS
    
    async def check_device_exists(self, device_id: str, time_window_minutes: int = 60) -> Tuple[bool, Dict]:
        """
        Check apakah device ada di InfluxDB dengan melihat data dalam time window tertentu
        Berdasarkan struktur: chipid tag, config_data/sensor_data measurements
        
        Args:
            device_id: ID device yang akan dicek (chipid)
            time_window_minutes: Window waktu untuk cek data (default 60 menit)
            
        Returns:
            (exists: bool, metadata: dict)
        """
        try:
            # Query untuk cek device dalam time window
            start_time = datetime.utcnow() - timedelta(minutes=time_window_minutes)
            start_time_str = start_time.strftime('%Y-%m-%dT%H:%M:%SZ')
            
            # Flux query untuk cari device berdasarkan chipid tag
            flux_query = f'''
from(bucket: "{self.config.BUCKET}")
  |> range(start: {start_time_str})
  |> filter(fn: (r) => r["{self.config.DEVICE_ID_TAG}"] == "{device_id}")
  |> group(columns: ["_measurement", "_field"])
  |> count()
  |> limit(n: 50)
'''
            
            logger.info(f"Querying InfluxDB for device {device_id} with query: {flux_query}")
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.config.HOST}/api/v2/query",
                    headers=self.config.get_headers(),
                    params={"org": self.config.ORG},
                    data=flux_query
                )
                
                logger.info(f"InfluxDB response status: {response.status_code}")
                
                if response.status_code == 200:
                    result_data = response.text
                    logger.debug(f"InfluxDB raw response: {result_data[:500]}...")
                    
                    # Parse CSV response
                    lines = result_data.strip().split('\n')
                    data_rows = []
                    
                    # Skip comments and header, find actual data
                    for line in lines:
                        if line.strip() and not line.startswith('#') and not line.startswith('_result'):
                            # Check if this line contains actual data (not header)
                            parts = line.split(',')
                            if len(parts) >= 4 and parts[0] != "_result":
                                data_rows.append(line)
                    
                    logger.info(f"Found {len(data_rows)} data rows for device {device_id}")
                    
                    if data_rows:
                        # Device ditemukan, parse metadata
                        metadata = await self._parse_device_metadata(device_id, result_data)
                        logger.info(f"Device {device_id} found in InfluxDB with {len(data_rows)} data points")
                        return True, metadata
                    
                    # Device tidak ditemukan dalam time window
                    logger.warning(f"Device {device_id} not found in InfluxDB within {time_window_minutes} minutes")
                    return False, {
                        "error": "NO_RECENT_DATA",
                        "message": f"Device {device_id} tidak mengirim data dalam {time_window_minutes} menit terakhir",
                        "checked_window": f"{time_window_minutes} minutes",
                        "bucket": self.config.BUCKET,
                        "last_check": datetime.utcnow().isoformat()
                    }
                
                elif response.status_code == 401:
                    logger.error("InfluxDB authentication failed")
                    return False, {
                        "error": "AUTH_FAILED",
                        "message": "Gagal autentikasi ke InfluxDB",
                        "suggestion": "Periksa token InfluxDB"
                    }
                
                elif response.status_code == 404:
                    logger.error(f"InfluxDB bucket '{self.config.BUCKET}' not found")
                    return False, {
                        "error": "BUCKET_NOT_FOUND",
                        "message": f"Bucket '{self.config.BUCKET}' tidak ditemukan",
                        "suggestion": "Periksa konfigurasi bucket InfluxDB"
                    }
                
                else:
                    logger.error(f"InfluxDB query failed: {response.status_code} - {response.text}")
                    return False, {
                        "error": "QUERY_FAILED",
                        "message": f"Query InfluxDB gagal: {response.status_code}",
                        "response_text": response.text[:200],
                        "suggestion": "Coba lagi dalam beberapa saat"
                    }
                    
        except httpx.TimeoutException:
            logger.error(f"InfluxDB timeout for device {device_id}")
            return False, {
                "error": "TIMEOUT",
                "message": "Timeout saat mengakses InfluxDB",
                "suggestion": "Coba lagi dalam beberapa saat"
            }
            
        except Exception as e:
            logger.error(f"Unexpected error checking device {device_id}: {str(e)}")
            return False, {
                "error": "UNEXPECTED_ERROR",
                "message": f"Error tidak terduga: {str(e)}",
                "suggestion": "Hubungi administrator sistem"
            }
    
    async def _parse_device_metadata(self, device_id: str, csv_data: str) -> Dict:
        """
        Parse metadata device dari CSV response InfluxDB
        Struktur CSV: result, table, _start, _stop, _time, _value, _field, _measurement, chipid
        """
        try:
            lines = csv_data.strip().split('\n')
            measurements = set()
            fields = set()
            total_points = 0
            
            # Find the header line
            header_idx = -1
            for i, line in enumerate(lines):
                if line.startswith('_result') or line.startswith(',_result'):
                    header_idx = i
                    break
            
            if header_idx >= 0:
                header = lines[header_idx].split(',')
                logger.debug(f"CSV Header: {header}")
                
                # Find column indices
                measurement_idx = -1
                field_idx = -1
                chipid_idx = -1
                
                for i, col in enumerate(header):
                    if col == '_measurement':
                        measurement_idx = i
                    elif col == '_field':
                        field_idx = i
                    elif col == self.config.DEVICE_ID_TAG:
                        chipid_idx = i
                
                # Parse data rows
                for line in lines[header_idx + 1:]:
                    if line.strip() and not line.startswith('#'):
                        parts = line.split(',')
                        if len(parts) > max(measurement_idx, field_idx, chipid_idx):
                            if measurement_idx >= 0:
                                measurements.add(parts[measurement_idx])
                            if field_idx >= 0:
                                fields.add(parts[field_idx])
                            total_points += 1
            
            return {
                "device_id": device_id,
                "measurements": list(measurements),
                "fields": list(fields),
                "total_data_points": total_points,
                "bucket": self.config.BUCKET,
                "last_check": datetime.utcnow().isoformat(),
                "status": "ACTIVE"
            }
            
        except Exception as e:
            logger.error(f"Error parsing device metadata: {str(e)}")
            return {
                "device_id": device_id,
                "error": "PARSE_ERROR",
                "message": f"Error parsing metadata: {str(e)}",
                "last_check": datetime.utcnow().isoformat()
            }
    
    async def get_device_last_activity(self, device_id: str) -> Optional[datetime]:
        """
        Get timestamp of last activity untuk device
        """
        try:
            # Query untuk get last timestamp
            flux_query = f'''
from(bucket: "{self.config.BUCKET}")
  |> range(start: -24h)
  |> filter(fn: (r) => r["{self.config.DEVICE_ID_TAG}"] == "{device_id}")
  |> sort(columns: ["_time"], desc: true)
  |> limit(n: 1)
'''
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.config.HOST}/api/v2/query",
                    headers=self.config.get_headers(),
                    params={"org": self.config.ORG},
                    data=flux_query
                )
                
                if response.status_code == 200:
                    result_data = response.text
                    lines = result_data.strip().split('\n')
                    
                    # Find header and time column
                    header_idx = -1
                    for i, line in enumerate(lines):
                        if line.startswith('_result') or line.startswith(',_result'):
                            header_idx = i
                            break
                    
                    if header_idx >= 0:
                        header = lines[header_idx].split(',')
                        time_idx = -1
                        for i, col in enumerate(header):
                            if col == '_time':
                                time_idx = i
                                break
                        
                        # Get first data row
                        for line in lines[header_idx + 1:]:
                            if line.strip() and not line.startswith('#'):
                                parts = line.split(',')
                                if len(parts) > time_idx and time_idx >= 0:
                                    timestamp_str = parts[time_idx]
                                    try:
                                        # Parse ISO timestamp
                                        return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                                    except:
                                        continue
                    
            return None
            
        except Exception as e:
            logger.error(f"Error getting last activity for {device_id}: {str(e)}")
            return None
    
    async def validate_device_for_registration(self, device_id: str) -> Tuple[bool, str, Dict]:
        """
        Comprehensive validation untuk device registration
        
        Returns:
            (is_valid: bool, message: str, metadata: dict)
        """
        try:
            # Check if device exists in recent data (last 60 minutes)
            exists, metadata = await self.check_device_exists(device_id, time_window_minutes=60)
            
            if not exists:
                # Try extended window (last 24 hours)
                exists_extended, metadata_extended = await self.check_device_exists(device_id, time_window_minutes=1440)
                
                if exists_extended:
                    return False, f"Device {device_id} ditemukan di InfluxDB tapi tidak mengirim data dalam 1 jam terakhir. Device mungkin offline.", metadata_extended
                else:
                    return False, f"Device {device_id} tidak ditemukan di bucket '{self.config.BUCKET}'. Pastikan device sudah mengirim data sensor dengan chipid yang benar.", metadata
            
            # Device exists and sending recent data
            last_activity = await self.get_device_last_activity(device_id)
            if last_activity:
                metadata["last_activity"] = last_activity.isoformat()
                time_diff = datetime.utcnow() - last_activity.replace(tzinfo=None)
                metadata["minutes_since_last_activity"] = int(time_diff.total_seconds() / 60)
            
            return True, f"Device {device_id} terverifikasi di InfluxDB bucket '{self.config.BUCKET}' dan aktif mengirim data", metadata
            
        except Exception as e:
            logger.error(f"Error validating device {device_id}: {str(e)}")
            return False, f"Error saat memvalidasi device: {str(e)}", {"error": str(e)}