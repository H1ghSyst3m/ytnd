# ytnd/syncthing_client.py
"""
Minimal Syncthing client that provides only the needed functionality for YTND.
"""
from __future__ import annotations
import requests, json, time
from pathlib import Path
from typing import Dict, Any
from .config import SYNCTHING_API, SYNCTHING_TOKEN
from .utils import logger

H = {"X-API-Key": SYNCTHING_TOKEN}
REQUEST_TIMEOUT = 10

class SyncthingError(Exception):
    """Base exception for Syncthing client errors."""
    pass

class SyncthingClient:
    def __init__(self):
        self._my_id = None

    @property
    def my_id(self) -> str:
        if not self._my_id:
            try:
                r = requests.get(f"{SYNCTHING_API}/system/status", headers=H, timeout=REQUEST_TIMEOUT)
                r.raise_for_status()
                self._my_id = r.json()["myID"]
            except requests.exceptions.Timeout:
                logger.error("Syncthing API request timed out while fetching system status")
                raise SyncthingError("Syncthing API timeout")
            except requests.exceptions.RequestException as e:
                logger.error("Syncthing API request failed: %s", e)
                raise SyncthingError(f"Syncthing API error: {e}")
            except (KeyError, ValueError) as e:
                logger.error("Invalid response from Syncthing API: %s", e)
                raise SyncthingError("Invalid Syncthing API response")
        return self._my_id

    def _get_config(self) -> Dict[str, Any]:
        try:
            r = requests.get(f"{SYNCTHING_API}/config", headers=H, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.Timeout:
            logger.error("Syncthing API request timed out while fetching config")
            raise SyncthingError("Syncthing API timeout")
        except requests.exceptions.RequestException as e:
            logger.error("Syncthing API request failed: %s", e)
            raise SyncthingError(f"Syncthing API error: {e}")
        except ValueError as e:
            logger.error("Invalid JSON response from Syncthing API: %s", e)
            raise SyncthingError("Invalid Syncthing API response")

    def _save_config(self, cfg: Dict[str, Any]):
        try:
            r = requests.put(f"{SYNCTHING_API}/config", headers=H,
                             data=json.dumps(cfg), timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            requests.post(f"{SYNCTHING_API}/config/reload", headers=H, timeout=REQUEST_TIMEOUT)
        except requests.exceptions.Timeout:
            logger.error("Syncthing API request timed out while saving config")
            raise SyncthingError("Syncthing API timeout")
        except requests.exceptions.RequestException as e:
            logger.error("Syncthing API request failed: %s", e)
            raise SyncthingError(f"Syncthing API error: {e}")

    def ensure_device(self, device_id: str, name: str | None = None):
        if not device_id or len(device_id) < 50:
            raise ValueError("Invalid device_id format")
        
        try:
            cfg = self._get_config()
            if not any(d["deviceID"] == device_id for d in cfg["devices"]):
                cfg["devices"].append({
                    "deviceID": device_id,
                    "name": name or device_id,
                    "addresses": ["dynamic"],
                    "compression": "metadata"
                })
                self._save_config(cfg)
                logger.info("Syncthing: Device %s added.", device_id)
        except SyncthingError:
            raise
        except Exception as e:
            logger.error("Failed to ensure device: %s", e)
            raise SyncthingError(f"Failed to ensure device: {e}")

    def ensure_folder(self, folder_id: str, path: Path, remote_device: str):
        if not folder_id or "/" in folder_id or "\\" in folder_id:
            raise ValueError("Invalid folder_id")
        if not path or not path.exists():
            raise ValueError("Invalid or non-existent path")
        
        try:
            cfg = self._get_config()
            folder = next((f for f in cfg["folders"] if f["id"] == folder_id), None)

            if folder is None:
                folder = {
                    "id": folder_id,
                    "label": folder_id,
                    "path": str(path),
                    "type": "sendonly",
                    "devices": [
                        {"deviceID": self.my_id},
                        {"deviceID": remote_device}
                    ],
                    "fsWatcherEnabled": True,
                    "fsWatcherDelay": 10
                }
                cfg["folders"].append(folder)
                logger.info("Syncthing: Folder %s created (%s)", folder_id, path)
            else:
                if not any(d["deviceID"] == remote_device for d in folder["devices"]):
                    folder["devices"].append({"deviceID": remote_device})
                    logger.info("Syncthing: Device %s added to folder %s.",
                                remote_device, folder_id)

            self._save_config(cfg)
        except SyncthingError:
            raise
        except Exception as e:
            logger.error("Failed to ensure folder: %s", e)
            raise SyncthingError(f"Failed to ensure folder: {e}")

    def rescan(self, folder_id: str):
        try:
            r = requests.post(f"{SYNCTHING_API}/db/scan",
                              headers=H, params={"folder": folder_id}, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
        except requests.exceptions.Timeout:
            logger.error("Syncthing API request timed out while rescanning folder")
            raise SyncthingError("Syncthing API timeout")
        except requests.exceptions.RequestException as e:
            logger.error("Syncthing API request failed during rescan: %s", e)
            raise SyncthingError(f"Syncthing API error: {e}")

    def folder_status(self, folder_id: str) -> Dict[str, Any]:
        try:
            r = requests.get(f"{SYNCTHING_API}/db/status",
                             headers=H, params={"folder": folder_id}, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.Timeout:
            logger.error("Syncthing API request timed out while fetching folder status")
            raise SyncthingError("Syncthing API timeout")
        except requests.exceptions.RequestException as e:
            logger.error("Syncthing API request failed while fetching folder status: %s", e)
            raise SyncthingError(f"Syncthing API error: {e}")
        except ValueError as e:
            logger.error("Invalid JSON response from Syncthing API: %s", e)
            raise SyncthingError("Invalid Syncthing API response")
