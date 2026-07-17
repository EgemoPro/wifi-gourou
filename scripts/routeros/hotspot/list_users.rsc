# ============================================================
#  hotspot/list_users.rsc — WIFIZONE
#  Liste les comptes utilisateur hotspot
# ============================================================

:put "=== USERS ==="
:local count 0

:do {
    :local users [/ip hotspot user print as-value]
    :foreach user in=$users do={
        :local name ($user->"name")
        :local profile ($user->"profile")
        :local comment ($user->"comment")
        :local limitUptime ($user->"limit-uptime")
        :local limitBytesIn ($user->"limit-bytes-in")
        :local limitBytesOut ($user->"limit-bytes-out")
        :local disabled ($user->"disabled")

        :if ($comment = "") do={ :set comment "-" }
        :if ($limitUptime = "") do={ :set limitUptime "-" }

        :put ("name=" . $name . "|profile=" . $profile . \
              "|comment=" . $comment . "|uptime_limit=" . $limitUptime . \
              "|data_limit_in=" . $limitBytesIn . "|data_limit_out=" . $limitBytesOut . \
              "|disabled=" . $disabled)
        :set count ($count + 1)
    }
} on-error={
    :put "hotspot_users_error=query_failed"
}

:put "=== END ==="
:put ("total=" . $count)
