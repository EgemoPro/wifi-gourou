# ============================================================
#  network/list_wireless.rsc — WIFIZONE
#  Liste les clients WiFi connectés (Wave2 + Legacy)
#  Lecture seule — ne modifie rien
# ============================================================

:put "=== WIRELESS_CLIENTS ==="
:local totalClients 0

# WiFi Wave2 (interface wifi) — package wifi-qcom / wifi-qcom-ac
:do {
    :local wifCount [/interface/wifi/registration-table/print count-only]
    :put ("wifi_wave2_count=" . $wifCount)

    :if ($wifCount > 0) do={
        :local regList [/interface/wifi/registration-table/print as-value]
        :foreach reg in=$regList do={
            :local mac ($reg->"mac-address")
            :local signal ($reg->"signal")
            :local iface ($reg->"interface")
            :local uptime ($reg->"uptime")
            :local ssid ($reg->"ssid")

            :put ("type=wave2|mac=" . $mac . "|signal=" . $signal . \
                  "|interface=" . $iface . "|uptime=" . $uptime . \
                  "|ssid=" . $ssid)
            :set totalClients ($totalClients + 1)
        }
    }
} on-error={
    :put "wifi_wave2=unsupported"
}

# WiFi Legacy (interface wireless) — package wireless (obsolète)
:do {
    :local legacyCount [/interface wireless registration-table print count-only]
    :put ("wifi_legacy_count=" . $legacyCount)

    :if ($legacyCount > 0) do={
        :local regList [/interface wireless registration-table print as-value]
        :foreach reg in=$regList do={
            :local mac ($reg->"mac-address")
            :local signal ($reg->"signal-strength")
            :local iface ($reg->"interface")
            :local uptime ($reg->"uptime")

            :put ("type=legacy|mac=" . $mac . "|signal=" . $signal . \
                  "|interface=" . $iface . "|uptime=" . $uptime)
            :set totalClients ($totalClients + 1)
        }
    }
} on-error={
    :put "wifi_legacy=unsupported"
}

:put "=== END ==="
:put ("total_wireless_clients=" . $totalClients)
