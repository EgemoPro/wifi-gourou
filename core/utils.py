"""
core/utils.py — Utilitaires partagés
"""
import re
from datetime import datetime, timezone


def now_iso() -> str:
    """Retourne le timestamp ISO 8601 courant."""
    return datetime.now(timezone.utc).isoformat()


def parse_bytes(value: str | int | None, default: int = 0) -> int:
    """
    Convertit une chaîne de taille RouterOS en bytes.
    Exemples : '10.0 MiB' → 10485760, '500.0 KiB' → 512000
    """
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return int(value)
    value = str(value).strip()
    if not value:
        return default
    multipliers = {"b": 1, "kib": 1024, "mib": 1024**2, "gib": 1024**3}
    value_lower = value.lower()
    # Trier par longueur de suffixe décroissante pour matcher "kib" avant "b"
    for suffix in sorted(multipliers, key=len, reverse=True):
        mult = multipliers[suffix]
        if value_lower.endswith(suffix):
            try:
                num = float(value_lower[: -len(suffix)].strip())
                return int(num * mult)
            except ValueError:
                return default
    try:
        return int(float(value))
    except ValueError:
        return default


def validate_mac(mac: str) -> bool:
    """Valide un format MAC address (AA:BB:CC:DD:EE:FF ou avec tirets)."""
    return bool(re.match(r'^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$', mac.strip()))


def parse_routeros_output(output: str, key_field: str = "name") -> list[dict[str, str]]:
    """
    Parse la sortie clé:valeur typique de RouterOS (print without terse).
    Entrée : sortie brute avec lignes "clé: valeur"
    Retourne une liste de dicts.
    """
    result: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in output.strip().splitlines():
        line = line.strip()
        if not line:
            if current:
                result.append(current)
                current = {}
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().replace("-", "_")
        val = val.strip()
        if key and val:
            current[key] = val
    if current:
        result.append(current)
    return result


def parse_table_output(output: str) -> list[dict[str, str]]:
    """
    Parse la sortie tabulaire de RouterOS (Flags: ... columns ...).
    Retourne une liste de dicts.
    """
    lines = output.strip().splitlines()
    headers: list[str] = []
    rows: list[dict[str, str]] = []
    for line in lines:
        line = line.rstrip()
        if line.startswith("Flags:"):
            continue
        parts = line.split()
        if not parts:
            continue
        # Détection d'en-tête (première ligne non-flag avec mots-clés)
        if any(kw in line for kw in ["NAME", "NAME", "USER", "ADDRESS"]):
            if not headers and len(parts) > 2:
                headers = parts
            continue
        if headers and len(parts) >= len(headers):
            row = dict(zip(headers, parts[: len(headers)]))
            rows.append(row)
    return rows
