# ============================================================
#  hotspot/list_vouchers.rsc — WIFIZONE
#  Liste les vouchers hotspot générés
# ============================================================

:put "=== VOUCHERS ==="
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

        :put ("user=" . $name . "|profile=" . $profile . \
              "|comment=" . $comment . "|uptime_limit=" . $limitUptime . \
              "|bytes_in_limit=" . $limitBytesIn . "|bytes_out_limit=" . $limitBytesOut . \
              "|used=" . $disabled)
        :set count ($count + 1)
    }
} on-error={
    :put "hotspot_vouchers_error=query_failed"
}

:put "=== END ==="
:put ("total=" . $count)
