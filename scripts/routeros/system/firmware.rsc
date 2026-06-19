# ============================================================
#  system/firmware.rsc — WIFIZONE
#  Infos firmware RouterBOARD
#  Lecture seule
# ============================================================

:put "=== FIRMWARE ==="

:do {
    :local rb [/system routerboard get]
    :put ("routerboard=" . ($rb->"routerboard"))
    :put ("model=" . ($rb->"model"))
    :put ("revision=" . ($rb->"revision"))
    :put ("serial=" . ($rb->"serial-number"))
    :put ("firmware_type=" . ($rb->"firmware-type"))
    :put ("current_firmware=" . ($rb->"current-firmware"))
    :put ("upgrade_firmware=" . ($rb->"upgrade-firmware"))
} on-error={
    :put "firmware=error"
}

# OS version (déjà dans info.rsc, mais pratique ici aussi)
:do {
    :put ("os_version=" . [/system resource get version])
    :put ("build_time=" . [/system resource get build-time])
    :put ("factory_software=" . [/system resource get factory-software])
} on-error={
    :put "os=error"
}

:put "=== END ==="
