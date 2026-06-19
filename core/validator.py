"""
core/validator.py — Validation des paramètres d'actions

Valide les paramètres reçus dans une requête de commande
contre la définition de l'action dans le registre.
"""
import re
import logging
from typing import Any, Optional

from core.registry import lookup

logger = logging.getLogger("validator")


class ValidationError(Exception):
    """Erreur de validation des paramètres."""

    def __init__(self, message: str, field: Optional[str] = None):
        self.field = field
        super().__init__(message)


def validate_action(action_name: str) -> dict[str, Any]:
    """
    Vérifie que l'action existe dans le registre.
    Retourne la définition complète.
    Lève ValidationError si l'action est inconnue.
    """
    action_def = lookup(action_name)
    if action_def is None:
        raise ValidationError(
            f"Action inconnue : '{action_name}'. "
            f"Utilisez GET /actions pour voir la liste."
        )
    return action_def


def validate_params(
    params: dict[str, Any],
    action_def: dict[str, Any],
) -> dict[str, Any]:
    """
    Valide et normalise les paramètres d'une action.

    1. Vérifie les paramètres requis
    2. Applique les valeurs par défaut
    3. Valide les types
    4. Valide les contraintes (max_length, min/max, pattern)

    Retourne le dict des paramètres normalisés.
    Lève ValidationError en cas de problème.
    """
    param_defs = action_def.get("params", [])
    allowed = {p["name"] for p in param_defs}
    normalized: dict[str, Any] = {}

    # Valeurs par défaut
    for p in param_defs:
        if "default" in p and p["name"] not in params:
            normalized[p["name"]] = p["default"]

    # Paramètres fournis
    for key, value in params.items():
        if key not in allowed:
            logger.warning(f"Paramètre inconnu ignoré : {key}")
            continue

        p_def = next((p for p in param_defs if p["name"] == key), None)
        if p_def is None:
            continue

        # Validation du type
        expected_type = p_def.get("type", "string")

        if expected_type == "string":
            if not isinstance(value, str):
                value = str(value)
            max_len = p_def.get("max_length")
            if max_len and len(value) > max_len:
                raise ValidationError(
                    f"'{key}' trop long ({len(value)} > {max_len})",
                    field=key,
                )
            pattern = p_def.get("pattern")
            if pattern and not re.match(pattern, value):
                raise ValidationError(
                    f"'{key}' ne correspond pas au format attendu",
                    field=key,
                )

        elif expected_type == "int":
            try:
                value = int(value)
            except (ValueError, TypeError):
                raise ValidationError(
                    f"'{key}' doit être un entier",
                    field=key,
                )
            min_val = p_def.get("min")
            max_val = p_def.get("max")
            if min_val is not None and value < min_val:
                raise ValidationError(
                    f"'{key}' minimum {min_val}",
                    field=key,
                )
            if max_val is not None and value > max_val:
                raise ValidationError(
                    f"'{key}' maximum {max_val}",
                    field=key,
                )

        elif expected_type == "bool":
            if isinstance(value, bool):
                pass
            elif isinstance(value, str):
                value = value.lower() in ("true", "1", "yes", "on")
            else:
                value = bool(value)

        normalized[key] = value

    # Vérifier les requis
    for p in param_defs:
        if p.get("required", False) and p["name"] not in normalized:
            raise ValidationError(
                f"Paramètre requis manquant : '{p['name']}'",
                field=p["name"],
            )

    return normalized



