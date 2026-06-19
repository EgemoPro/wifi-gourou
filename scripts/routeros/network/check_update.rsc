# ============================================================
#  network/check_update.rsc — WIFIZONE
#  Vérifie la disponibilité d'une mise à jour RouterOS
#  Lecture seule — ne modifie rien
# ============================================================

:put "=== ROUTEROS_UPDATE ==="

:do {
    /system/package/update/check-for-updates
} on-error={
    :put "update_check=failed"
}

:do {
    :local installed [/system/package/update/get installed-version]
    :local latest [/system/package/update/get latest-version]
    :local channel [/system/package/update/get channel]
    :local status [/system/package/update/get status]

    :put ("installed_version=" . $installed)
    :put ("latest_version=" . $latest)
    :put ("channel=" . $channel)
    :put ("status=" . $status)
} on-error={
    :put "update_check=error"
}

:put "=== END ==="
