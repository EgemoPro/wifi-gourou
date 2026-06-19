# ============================================================
#  hotspot/list_active.rsc — WIFIZONE
#  Liste les utilisateurs hotspot actifs
# ============================================================

:put "=== ACTIVE_USERS ==="
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

        :if ($loginBy = "") do={ :set loginBy "N/A" }

        :put ("user=" . $user . "|address=" . $address . "|mac=" . $macAddr . \
              "|uptime=" . $uptime . "|bytes_in=" . $bytesIn . \
              "|bytes_out=" . $bytesOut . "|profile=" . $profile . \
              "|login_by=" . $loginBy)
        :set count ($count + 1)
    }
} on-error={
    :put "hotspot_active_error=query_failed"
}

:put "=== END ==="
:put ("total=" . $count)
