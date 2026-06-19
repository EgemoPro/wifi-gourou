# ============================================================
#  hotspot/delete_user.rsc — WIFIZONE
#  Supprime un utilisateur hotspot
# ============================================================

:local username "$username"

:local userid [/ip hotspot user find name=$username]
:if ([:len $userid] = 0) do={
    :put "USER_NOT_FOUND"
    :error "Utilisateur introuvable"
}

/ip hotspot user remove $userid

:put "USER_DELETED"
:put "username=$username"
