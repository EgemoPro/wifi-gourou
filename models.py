"""
models.py — Modèles de données partagés
Ajout des modèles ActionRequest/ActionResponse pour la nouvelle architecture.
"""
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from datetime import datetime


class MetricsData(BaseModel):
    site_id:        str
    site_name:      str
    timestamp:      str
    cpu_load:       Optional[float] = None
    memory_free:    Optional[int]   = None
    memory_total:   Optional[int]   = None
    uptime:         Optional[str]   = None
    ros_version:    Optional[str]   = None
    board_name:     Optional[str]   = None
    active_users:   Optional[int]   = None
    temperature:    Optional[float] = None
    voltage:        Optional[float] = None


class HotspotClient(BaseModel):
    user:        str
    ip:          Optional[str] = None
    mac:         Optional[str] = None
    uptime:      Optional[str] = None
    bytes_in:    int = 0
    bytes_out:   int = 0
    profile:     Optional[str] = None
    client_type: str = "hotspot"


class ClientsData(BaseModel):
    site_id:   str
    site_name: str
    timestamp: str
    count:     int
    clients:   List[HotspotClient] = []


class AlertData(BaseModel):
    site_id:    str
    site_name:  str
    timestamp:  str
    alert_type: str
    message:    str
    data:       Dict[str, Any] = {}


class CommandRequest(BaseModel):
    """Ancien format (rétrocompatible)."""
    command: str
    params:  Dict[str, Any] = {}


class ActionRequest(BaseModel):
    """Nouveau format d'action unifiée."""
    action:     str
    payload:    Dict[str, Any] = {}
    mode:       Optional[str] = None  # "execute" (default), "preview"
    command_id: Optional[str] = None  # pour idempotence (n8n rejeu)


class CommandResult(BaseModel):
    """Ancien format de résultat (rétrocompatible)."""
    site_id:   str
    command:   str
    status:    str
    result:    Dict[str, Any] = {}
    timestamp: str


class MikroTikRawAlert(BaseModel):
    site:  str
    type:  str = Field(max_length=100)
    value: str = Field(max_length=500)


class UserBloatData(BaseModel):
    site_id:     str
    site_name:   str
    timestamp:   str
    total_users: int
    disabled:    int
    never_used:  int
    alert:       bool


class SchedulerData(BaseModel):
    site_id:    str
    site_name:  str
    timestamp:  str
    count:      int
    alert:      bool
    schedulers: List[Dict[str, Any]] = []


class BackupResult(BaseModel):
    site_id:   str
    site_name: str
    timestamp: str
    status:    str
    filename:  Optional[str] = None
    size_kb:   Optional[int] = None
    error:     Optional[str] = None


class SiteRegistration(BaseModel):
    site_id:       str
    site_name:     str
    agent_url:     str
    mikrotik_host: str
    active:        bool = True
