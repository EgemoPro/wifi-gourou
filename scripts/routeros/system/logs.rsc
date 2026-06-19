# ============================================================
#  system/logs.rsc — WIFIZONE
#  Récupère les logs récents (critiques + erreurs)
#  Lecture seule — utilise print direct vers stdout
# ============================================================

:put "=== LOGS ==="

:do {
    :put "--- CRITICAL ---"
    /log print where topics~"critical"
} on-error={
    :put "critical=error"
}

:do {
    :put "--- ERROR ---"
    /log print where topics~"error"
} on-error={
    :put "error_log=error"
}

:do {
    :put "--- RECENT ---"
    /log print
} on-error={
    :put "recent=error"
}

:put "=== END ==="
