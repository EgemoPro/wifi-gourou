# ============================================================
#  network/top_users.rsc — WIFIZONE
#  Consommateurs réseau : files d'attente + sessions hotspot
#  Classement par trafic descendant (rx_bytes)
# ============================================================

:put "=== QUEUES ==="
:local qCount 0

:do {
    :foreach q in=[/queue simple print as-value] do={
        :local name ($q->"name")
        :local target ($q->"target")
        :local rate ($q->"rate")
        :local totalBytes ($q->"total-bytes")
        :local packets ($q->"total-packets")

        :if ($name = "") do={ :set name "-" }
        :if ($rate = "") do={ :set rate "-" }
        :if ($totalBytes = "") do={ :set totalBytes "0" }

        :put ("name=" . $name . "|target=" . $target . \
              "|rate=" . $rate . "|bytes=" . $totalBytes . \
              "|packets=" . $packets)
        :set qCount ($qCount + 1)
    }
} on-error={
    :put "queues_error=query_failed"
}

:put "=== HOTSPOT_ACTIVE ==="
:local hCount 0

:do {
    :foreach u in=[/ip hotspot active print as-value] do={
        :local user ($u->"user")
        :local address ($u->"address")
        :local mac ($u->"mac-address")
        :local uptime ($u->"uptime")
        :local bytesIn ($u->"bytes-in")
        :local bytesOut ($u->"bytes-out")
        :local packetsIn ($u->"packets-in")
        :local packetsOut ($u->"packets-out")

        :if ($user = "") do={ :set user "-" }
        :put ("user=" . $user . "|address=" . $address . \
              "|mac=" . $mac . "|uptime=" . $uptime . \
              "|rx_bytes=" . $bytesIn . "|tx_bytes=" . $bytesOut . \
              "|rx_packets=" . $packetsIn . "|tx_packets=" . $packetsOut)
        :set hCount ($hCount + 1)
    }
} on-error={
    :put "hotspot_error=query_failed"
}

:put "=== END ==="
:put ("queues=" . $qCount . "|hotspot_active=" . $hCount)
