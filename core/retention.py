"""
core/retention.py — Purge automatique des fichiers générés par l'agent.

Sans purge, les backups du routeur et les bons PDF s'accumulent dans DATA_DIR
jusqu'à remplir le disque (clé USB d'un container MikroTik, notamment).

Règles (par dossier) :
  - les `keep_min` fichiers les plus récents ne sont JAMAIS supprimés ;
  - les autres sont supprimés s'ils ont plus de `max_age_days` jours ;
  - puis, si le dossier dépasse `max_total_mb`, on supprime les plus anciens
    jusqu'à repasser sous le plafond (toujours en protégeant `keep_min`).
Une valeur de 0 désactive le critère correspondant.

Seuls les fichiers ordinaires qui correspondent aux motifs donnés sont touchés :
jamais de dossier, jamais de lien symbolique, jamais un autre type de fichier.
"""

import logging
import time
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger("retention")

_DAY = 86400.0
_MB = 1024 * 1024


def purge_directory(
    directory: Path | str,
    *,
    patterns: Iterable[str] = ("*",),
    max_age_days: float = 0,
    max_total_mb: float = 0,
    keep_min: int = 0,
    now: Optional[float] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Applique la rétention à un dossier. Retourne un résumé (jamais d'exception)."""
    directory = Path(directory)
    summary: dict[str, Any] = {
        "directory": str(directory),
        "deleted": 0,
        "freed_bytes": 0,
        "kept": 0,
        "errors": 0,
        "dry_run": dry_run,
    }
    if not directory.is_dir():
        return summary

    now = time.time() if now is None else now

    # Inventaire : fichiers ordinaires uniquement, du plus récent au plus ancien
    files: list[tuple[Path, float, int]] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for p in directory.glob(pattern):
            if p in seen:
                continue
            seen.add(p)
            try:
                if p.is_symlink() or not p.is_file():
                    continue
                st = p.stat()
                files.append((p, st.st_mtime, st.st_size))
            except OSError:
                summary["errors"] += 1
    files.sort(key=lambda f: f[1], reverse=True)

    keep_min = max(0, int(keep_min))
    protected = files[:keep_min]
    candidates = files[keep_min:]          # du plus récent au plus ancien
    to_delete: list[tuple[Path, float, int]] = []

    # 1) Âge
    if max_age_days and max_age_days > 0:
        limit = now - max_age_days * _DAY
        to_delete += [f for f in candidates if f[1] < limit]
        candidates = [f for f in candidates if f[1] >= limit]

    # 2) Taille totale (on retire d'abord les plus anciens)
    if max_total_mb and max_total_mb > 0:
        total = sum(f[2] for f in protected) + sum(f[2] for f in candidates)
        cap = max_total_mb * _MB
        while total > cap and candidates:
            oldest = candidates.pop()      # dernier = le plus ancien
            to_delete.append(oldest)
            total -= oldest[2]

    for path, _mtime, size in to_delete:
        try:
            if not dry_run:
                path.unlink()
            summary["deleted"] += 1
            summary["freed_bytes"] += size
            logger.info(f"Rétention : {'(simulation) ' if dry_run else ''}supprimé {path.name}")
        except FileNotFoundError:
            pass                           # supprimé entre-temps : sans importance
        except OSError as e:
            summary["errors"] += 1
            logger.warning(f"Rétention : suppression impossible {path.name} : {e}")

    summary["kept"] = len(files) - summary["deleted"]
    return summary


def run_retention(config: dict, backup_dir: Path | str, voucher_dir: Path | str) -> dict[str, Any]:
    """Purge backups et bons PDF selon CONFIG['retention']. Ne lève jamais d'exception."""
    ret = (config or {}).get("retention", {}) or {}
    out: dict[str, Any] = {}
    try:
        b = ret.get("backup", {})
        out["backups"] = purge_directory(
            backup_dir,
            patterns=("*.backup",),
            max_age_days=b.get("max_age_days", 30),
            max_total_mb=b.get("max_total_mb", 200),
            keep_min=b.get("keep_min", 3),
        )
        v = ret.get("voucher", {})
        out["vouchers"] = purge_directory(
            voucher_dir,
            patterns=("*.pdf",),
            max_age_days=v.get("max_age_days", 30),
            max_total_mb=v.get("max_total_mb", 200),
            keep_min=v.get("keep_min", 0),
        )
    except Exception as e:  # la maintenance ne doit jamais faire échouer l'appelant
        logger.error(f"Rétention : erreur inattendue : {e}", exc_info=True)
        out["error"] = str(e)
    freed = sum(d.get("freed_bytes", 0) for d in out.values() if isinstance(d, dict))
    deleted = sum(d.get("deleted", 0) for d in out.values() if isinstance(d, dict))
    if deleted:
        logger.info(f"Rétention : {deleted} fichier(s) supprimé(s), {freed // 1024} Ko libérés")
    return out
