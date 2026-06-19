# ============================================================
#  diagnostics/health.rsc — WIFIZONE
#  Récupère les métriques de santé du routeur
#  Format clé=valeur pour parsing par l'agent
# ============================================================

:put "=== HEALTH ==="

# CPU, mémoire, uptime
:local resource [/system resource get]
:put ("cpu_load=" . [/system resource get cpu-load])
:put ("free_memory=" . [/system resource get free-memory])
:put ("total_memory=" . [/system resource get total-memory])
:put ("uptime=" . [/system resource get uptime])
:put ("ros_version=" . [/system resource get version])
:put ("board_name=" . [/system resource get board-name])

# Temperature (le nom varie selon modèle: temperature / cpu-temperature / cpu-temp)
:do {
    :local temp "N/A"
    :foreach entry in=[/system health print as-value] do={
        :local name ($entry->"name")
        :if (($name = "cpu-temperature") or ($name = "temperature") or ($name = "cpu-temp") or ($name = "board-temperature")) do={
            :set temp ($entry->"value")
        }
    }
    :put ("temperature=" . $temp)
} on-error={
    :put "temperature=N/A"
}

# Voltage (si disponible - le nom varie aussi)
:do {
    :local voltage "N/A"
    :foreach entry in=[/system health print as-value] do={
        :local name ($entry->"name")
        :if (($name = "voltage") or ($name = "system-voltage")) do={
            :set voltage ($entry->"value")
        }
    }
    :put ("voltage=" . $voltage)
} on-error={
    :put "voltage=N/A"
}

# Clients actifs hotspot
:local hotspotCount 0
:do {
    :set hotspotCount [/ip hotspot active print count-only]
} on-error={}
:put ("hotspot_clients=" . $hotspotCount)

# Clients actifs PPP
:local pppCount 0
:do {
    :set pppCount [/ppp active print count-only]
} on-error={}
:put ("ppp_clients=" . $pppCount)

# Nombre total d'utilisateurs hotspot
:local totalUsers 0
:do {
    :set totalUsers [/ip hotspot user print count-only]
} on-error={}
:put ("total_users=" . $totalUsers)

:put "=== END ==="
