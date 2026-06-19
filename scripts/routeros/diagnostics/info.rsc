# ============================================================
#  diagnostics/info.rsc — WIFIZONE
#  Informations détaillées du système
# ============================================================

:put "=== SYSTEM_INFO ==="

:put ("identity=" . [/system identity get name])

:local resource [/system resource get]
:put ("cpu=" . [/system resource get cpu-load])
:put ("cpu_count=" . [/system resource get cpu-count])
:put ("cpu_frequency=" . [/system resource get cpu-frequency])
:put ("free_memory=" . [/system resource get free-memory])
:put ("total_memory=" . [/system resource get total-memory])
:put ("free_hdd=" . [/system resource get free-hdd-space])
:put ("total_hdd=" . [/system resource get total-hdd-space])
:put ("uptime=" . [/system resource get uptime])
:put ("version=" . [/system resource get version])
:put ("build_time=" . [/system resource get build-time])
:put ("board_name=" . [/system resource get board-name])
:put ("architecture=" . [/system resource get architecture-name])

# Licence
:do {
    :put ("software_id=" . [/system license get software-id])
    :put ("level=" . [/system license get level])
} on-error={}

:put "=== END ==="
