# ============================================================
#  network/unblock_mac.rsc — WIFIZONE
#  Débloque une adresse MAC (supprime la règle firewall)
#  Injecté par l'agent : :local mac
# ============================================================

:local mac "$mac"

# Vérifier si la MAC est bloquée
:local existing [/ip firewall filter find src-mac-address=$mac]
:if ([:len $existing] = 0) do={
    :put "MAC_NOT_FOUND"
    :error "MAC non trouvee"
}

/ip firewall filter remove $existing

:put "MAC_UNBLOCKED"
:put ("mac=" . $mac)
