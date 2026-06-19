# ============================================================
#  diagnostics/schedulers.rsc — WIFIZONE
#  Liste les scripts planifiés (scheduler)
# ============================================================

:put "=== SCHEDULERS ==="
:local count 0

:foreach s in=[/system scheduler find] do={
    :local name [/system scheduler get $s name]
    :local interval [/system scheduler get $s interval]
    :local startDate [/system scheduler get $s start-date]
    :local startTime [/system scheduler get $s start-time]
    :local runCount [/system scheduler get $s run-count]
    :local disabled [/system scheduler get $s disabled]

    :put ("name=" . $name . "|interval=" . $interval . \
          "|start_date=" . $startDate . "|start_time=" . $startTime . \
          "|run_count=" . $runCount . "|disabled=" . $disabled)
    :set count ($count + 1)
}

:put "=== END ==="
:put ("total=" . $count)
