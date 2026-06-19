# ============================================================
#  network/block_mac.rsc — WIFIZONE
#  Bloque une adresse MAC (via firewall filter)
#  Injecté par l'agent : :local mac, :local comment
#  Utilise /ip firewall filter add chain=forward src-mac-address=...
#  (les address-lists n'acceptent pas les MAC)
# ============================================================

:local mac "$mac"
:local comment "$comment"

:if ($comment = "") do={
    :set comment ("WIFIZONE - bloque le [/system clock get date]")
}

# Vérifier si déjà bloqué
:local existing [/ip firewall filter find src-mac-address=$mac]
:if ([:len $existing] > 0) do={
    :put "MAC_ALREADY_BLOCKED"
    :error "MAC deja bloquee"
}

/ip firewall filter add \
    chain=forward \
    src-mac-address=$mac \
    action=drop \
    comment=$comment

:put "MAC_BLOCKED"
:put ("mac=" . $mac)
