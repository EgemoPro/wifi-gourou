# ============================================================
#  hotspot/disable_user.rsc — WIFIZONE
#  Désactive un utilisateur hotspot (sans le supprimer)
# ============================================================

:local username "$username"

:local userid [/ip hotspot user find name=$username]
:if ([:len $userid] = 0) do={
    :put "USER_NOT_FOUND"
    :error "Utilisateur introuvable"
}

/ip hotspot user set disabled=yes $userid

:put "USER_DISABLED"
:put "username=$username"
