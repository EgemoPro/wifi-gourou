# ============================================================
#  system/uptime.rsc — WIFIZONE
#  Ressources système + uptime + historique plantages
# ============================================================

:put "=== RESOURCE ==="
:local uptimeStr [/system resource get uptime]
:local cpuLoad [/system resource get cpu-load]
:local freeMem [/system resource get free-memory]
:local totalMem [/system resource get total-memory]
:local freeHdd [/system resource get free-hdd-space]
:local totalHdd [/system resource get total-hdd-space]
:local cpuCount [/system resource get cpu-count]
:local cpuFreq [/system resource get cpu-frequency]
:local boardName [/system resource get board-name]
:local version [/system resource get version]

:put ("uptime=" . $uptimeStr . "|cpu_load=" . $cpuLoad . \
      "|free_memory=" . $freeMem . "|total_memory=" . $totalMem . \
      "|free_hdd=" . $freeHdd . "|total_hdd=" . $totalHdd . \
      "|cpu_count=" . $cpuCount . "|cpu_freq=" . $cpuFreq . \
      "|board=" . $boardName . "|version=" . $version)

:put "=== HISTORY ==="
:local hCount 0

:do {
    :foreach h in=[/system history print as-value] do={
        :local action ($h->"action")
        :local who ($h->"who")
        :local time ($h->"time")
        :local message ($h->"message")

        :if ($message = "") do={ :set message "-" }
        :if ($who = "") do={ :set who "-" }

        :put ("action=" . $action . "|who=" . $who . \
              "|time=" . $time . "|message=" . $message)
        :set hCount ($hCount + 1)
    }
} on-error={
    :put "history_error=query_failed"
}

:put "=== END ==="
:put ("sections=resource|history|total_history=" . $hCount)
