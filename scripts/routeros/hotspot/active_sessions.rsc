# ============================================================
#  hotspot/active_sessions.rsc — WIFIZONE
#  Sessions hotspot actives détaillées avec consommation
# ============================================================

:put "=== ACTIVE_SESSIONS ==="
:local count 0

:do {
    :local sessions [/ip hotspot active print as-value]
    :foreach session in=$sessions do={
        :local user ($session->"user")
        :local address ($session->"address")
        :local macAddr ($session->"mac-address")
        :local uptime ($session->"uptime")
        :local bytesIn ($session->"bytes-in")
        :local bytesOut ($session->"bytes-out")
        :local profile ($session->"profile")
        :local loginBy ($session->"login-by")
        :local idleTime ($session->"idle-time")
        :local idleTimeout ($session->"idle-timeout")

        :if ($loginBy = "") do={ :set loginBy "N/A" }
        :if ($idleTime = "") do={ :set idleTime "0s" }

        :put ("user=" . $user . "|address=" . $address . "|mac=" . $macAddr . \
              "|uptime=" . $uptime . "|bytes_in=" . $bytesIn . \
              "|bytes_out=" . $bytesOut . "|profile=" . $profile . \
              "|login_by=" . $loginBy . "|idle=" . $idleTime)
        :set count ($count + 1)
    }
} on-error={
    :put "hotspot_sessions_error=query_failed"
}

:put "=== END ==="
:put ("total=" . $count)
