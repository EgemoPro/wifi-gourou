# ============================================================
#  network/neighbors.rsc — WIFIZONE
#  Voisins réseau découverts (LLDP/CDP/MNDP)
# ============================================================

:put "=== NEIGHBORS ==="
:local count 0

:do {
    :foreach n in=[/ip neighbor print as-value] do={
        :local address ($n->"address")
        :local mac ($n->"mac-address")
        :local iface ($n->"interface")
        :local identity ($n->"identity")
        :local platform ($n->"platform")
        :local version ($n->"version")
        :local comment ($n->"comment")

        :if ($identity = "") do={ :set identity "-" }
        :if ($platform = "") do={ :set platform "-" }
        :if ($version = "") do={ :set version "-" }
        :if ($comment = "") do={ :set comment "" }

        :put ("address=" . $address . "|mac=" . $mac . \
              "|interface=" . $iface . "|identity=" . $identity . \
              "|platform=" . $platform . "|version=" . $version)
        :set count ($count + 1)
    }
} on-error={
    :put "neighbors_error=query_failed"
}

:put "=== END ==="
:put ("total=" . $count)
