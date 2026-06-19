# ============================================================
#  hotspot/enable_user.rsc — WIFIZONE
#  Réactive un utilisateur hotspot désactivé
# ============================================================

:local username "$username"

:local userid [/ip hotspot user find name=$username]
:if ([:len $userid] = 0) do={
    :put "USER_NOT_FOUND"
    :error "Utilisateur introuvable"
}

/ip hotspot user set disabled=no $userid

:put "USER_ENABLED"
:put "username=$username"
