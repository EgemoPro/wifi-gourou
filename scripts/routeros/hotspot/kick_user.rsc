# ============================================================
#  hotspot/kick_user.rsc — WIFIZONE
#  Déconnecte un utilisateur hotspot actif
# ============================================================

:local username "$username"

:local count 0
:local sessions [/ip hotspot active find user=$username]

:if ([:len $sessions] = 0) do={
    :put "USER_NOT_CONNECTED"
    :error "Utilisateur non connecte"
}

:foreach sessionId in=$sessions do={
    /ip hotspot active remove $sessionId
    :set count ($count + 1)
}

:put "USER_KICKED"
:put ("sessions_removed=" . $count)
:put "username=$username"
