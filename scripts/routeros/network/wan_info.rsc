# ============================================================
#  network/wan_info.rsc — WIFIZONE
#  Infos WAN (IP, passerelle, DNS)
#  Lecture seule
# ============================================================

:put "=== WAN_INFO ==="

# Adresse IP sur l'interface WAN (ether1)
:do {
    :foreach addr in=[/ip address print as-value] do={
        :local iface ($addr->"interface")
        :if ($iface = "ether1") do={
            :put ("wan_interface=" . $iface)
            :put ("wan_address=" . ($addr->"address"))
            :put ("wan_network=" . ($addr->"network"))
        }
    }
} on-error={
    :put "wan_address=error"
}

# Passerelle par défaut
:do {
    /ip route print where dst-address=0.0.0.0/0
} on-error={
    :put "gateway=error"
}

# DNS
:do {
    :put ("dns_servers=" . [/ip dns get servers])
} on-error={
    :put "dns_servers=error"
}

:do {
    :put ("dns_allow_remote=" . [/ip dns get allow-remote-requests])
} on-error={
    :put "dns_allow_remote=error"
}

:put "=== END ==="
