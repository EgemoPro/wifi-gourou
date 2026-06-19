"""
core/registry.py — Registre des actions

Charge le fichier config/commands.json et fournit :
  - lookup(action_name) → résout l'action (supports alias)
  - validate(action_name, params) → vérifie les paramètres requis
  - list_actions() → toutes les actions disponibles (pour n8n)
  - get_script_path(action) → chemin vers le fichier .rsc
"""
import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("registry")

# Chemin vers le fichier de registre
REGISTRY_PATH = Path(__file__).parent.parent / "config" / "commands.json"
# Répertoire des scripts RSC
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"

# Cache du registre (chargé une fois)
_registry: Optional[dict[str, Any]] = None
_actions: dict[str, Any] = {}
_alias_map: dict[str, str] = {}


def load_registry() -> dict[str, Any]:
    """Charge et met en cache le registre des actions."""
    global _registry, _actions, _alias_map

    if _registry is not None:
        return _registry

    if not REGISTRY_PATH.is_file():
        logger.warning(f"Registre introuvable : {REGISTRY_PATH}")
        _registry = {"actions": {}}
        _actions = {}
        return _registry

    with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
        _registry = json.load(f)

    # Construire les index
    _actions = _registry.get("actions", {})
    _alias_map = {}
    for action_name, action_def in _actions.items():
        # Indexer les alias (anciens noms de commandes)
        for alias in action_def.get("alias", []):
            _alias_map[alias] = action_name

    logger.debug(
        f"Registre chargé : {len(_actions)} actions, "
        f"{len(_alias_map)} alias"
    )
    return _registry


def reload() -> None:
    """Force le rechargement du registre (utile en dev)."""
    global _registry, _actions, _alias_map
    _registry = None
    _actions = {}
    _alias_map = {}
    load_registry()
    logger.info("Registre rechargé")


def lookup(action_name: str) -> Optional[dict[str, Any]]:
    """
    Résout une action par nom ou alias.
    Retourne la définition complète ou None si introuvable.
    """
    load_registry()

    # Chercher dans les actions
    if action_name in _actions:
        return _actions[action_name]

    # Chercher dans les alias
    if action_name in _alias_map:
        canonical = _alias_map[action_name]
        return _actions[canonical]

    return None


def resolve_name(action_name: str) -> Optional[str]:
    """
    Retourne le nom canonique d'une action
    (résout les alias vers le nom officiel).
    """
    load_registry()

    if action_name in _actions:
        return action_name
    if action_name in _alias_map:
        return _alias_map[action_name]
    return None


def get_script_path(action_def: dict[str, Any]) -> Optional[Path]:
    """
    Retourne le chemin absolu vers le fichier .rsc
    pour une action de type 'routeros'.
    """
    script_rel = action_def.get("script")
    if not script_rel:
        return None
    return SCRIPTS_DIR / "routeros" / script_rel


def list_actions() -> dict[str, Any]:
    """
    Retourne toutes les actions (sans les alias).
    Utile pour exposer le catalogue à n8n.
    """
    load_registry()
    return {
        name: {
            "description": act.get("description", ""),
            "danger": act.get("danger", "low"),
            "params": [
                {"name": p["name"], "required": p.get("required", False)}
                for p in act.get("params", [])
            ],
            "version": act.get("version", "1.0"),
        }
        for name, act in _actions.items()
    }


def get_capabilities() -> dict[str, Any]:
    """
    Catalogue complet des actions avec toutes les métadonnées.
    Utilisé par GET /capabilities pour la découverte par n8n.
    Accessible sans authentification API.
    """
    load_registry()
    return {
        "meta": _registry.get("meta", {}),
        "actions": {
            name: {
                "type": act.get("type", "routeros"),
                "script": act.get("script", ""),
                "handler": act.get("handler", ""),
                "description": act.get("description", ""),
                "danger": act.get("danger", "low"),
                "roles": act.get("roles", []),
                "timeout": act.get("timeout", 30),
                "version": act.get("version", "1.0"),
                "params": [
                    {
                        "name": p["name"],
                        "required": p.get("required", False),
                        "type": p.get("type", "string"),
                        "default": p.get("default"),
                        "max_length": p.get("max_length"),
                        "min": p.get("min"),
                        "max": p.get("max"),
                        "pattern": p.get("pattern"),
                    }
                    for p in act.get("params", [])
                ],
            }
            for name, act in _actions.items()
        }
    }



