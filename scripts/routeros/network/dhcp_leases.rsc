# ============================================================
#  network/dhcp_leases.rsc — WIFIZONE
#  Liste les baux DHCP actifs et non-actifs
# ============================================================

:put "=== LEASES ==="
:local count 0

:do {
    :foreach l in=[/ip dhcp-server lease print as-value] do={
        :local address ($l->"address")
        :local mac ($l->"mac-address")
        :local hostname ($l->"host-name")
        :local server ($l->"server")
        :local status ($l->"status")
        :local expires ($l->"expires-after")
        :local comment ($l->"comment")
        :local lastSeen ($l->"last-seen")

        :if ($hostname = "") do={ :set hostname "-" }
        :if ($comment = "") do={ :set comment "" }
        :if ($lastSeen = "") do={ :set lastSeen "never" }

        :put ("address=" . $address . "|mac=" . $mac . "|hostname=" . $hostname . \
              "|server=" . $server . "|status=" . $status . \
              "|expires=" . $expires . "|last_seen=" . $lastSeen)
        :set count ($count + 1)
    }
} on-error={
    :put "leases_error=query_failed"
}

:put "=== END ==="
:put ("total=" . $count)
