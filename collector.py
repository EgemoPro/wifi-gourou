"""
collector.py — Shim de rétrocompatibilité

Importe depuis workers.metrics (nouvelle architecture SSH).
Les anciens imports 'from collector import collect_metrics' continuent de fonctionner.
"""
from workers.metrics import (
    collect_metrics,
    collect_clients,
    check_bandwidth_abuse,
    check_router_online,
    check_user_bloat,
    check_scheduler_bloat,
)
