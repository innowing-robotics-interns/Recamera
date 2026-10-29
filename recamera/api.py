"""
REST API client for Seeed reCamera Supervisor management service (port 80).
"""

from typing import Any, Dict, List, Optional
import requests


class ReCameraAPI:
    """Interacts with the reCamera Supervisor HTTP REST API on port 80."""

    def __init__(self, camera_ip: str = "192.168.42.1", port: int = 80, token: Optional[str] = None):
        self.base_url = f"http://{camera_ip}:{port}/api"
        self.token = token
        self.session = requests.Session()

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = self.token
        return headers

    def login(self, username: str = "recamera", password: str = "recamera") -> bool:
        """Authenticate with the supervisor service and store the token."""
        url = f"{self.base_url}/userMgr/login"
        try:
            resp = self.session.post(url, json={"userName": username, "password": password}, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0 and "data" in data and "token" in data["data"]:
                    self.token = data["data"]["token"]
                    return True
        except Exception:
            pass
        return False

    def get_version(self) -> Dict[str, Any]:
        """Fetch system/firmware version information."""
        try:
            resp = self.session.get(f"{self.base_url}/version", headers=self._headers(), timeout=5)
            return resp.json() if resp.status_code == 200 else {}
        except Exception as e:
            return {"error": str(e)}

    def get_system_status(self) -> Dict[str, Any]:
        """Query CPU, memory, and runtime system metrics."""
        try:
            resp = self.session.get(f"{self.base_url}/deviceMgr/getSystemStatus", headers=self._headers(), timeout=5)
            return resp.json() if resp.status_code == 200 else {}
        except Exception as e:
            return {"error": str(e)}

    def get_device_info(self) -> Dict[str, Any]:
        """Fetch hardware and device information."""
        try:
            resp = self.session.get(f"{self.base_url}/deviceMgr/queryDeviceInfo", headers=self._headers(), timeout=5)
            return resp.json() if resp.status_code == 200 else {}
        except Exception as e:
            return {"error": str(e)}

    def list_models(self) -> List[Dict[str, Any]]:
        """List all compiled models installed on the camera."""
        try:
            resp = self.session.get(f"{self.base_url}/deviceMgr/getModelList", headers=self._headers(), timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("data", [])
        except Exception:
            pass
        return []

    def upload_model(self, file_path: str) -> Dict[str, Any]:
        """Upload a compiled .cvimodel directly to the device."""
        url = f"{self.base_url}/deviceMgr/uploadModel"
        headers = {}
        if self.token:
            headers["Authorization"] = self.token
        try:
            with open(file_path, "rb") as f:
                files = {"file": f}
                resp = self.session.post(url, files=files, headers=headers, timeout=60)
                return resp.json() if resp.status_code == 200 else {"status": resp.status_code}
        except Exception as e:
            return {"error": str(e)}
