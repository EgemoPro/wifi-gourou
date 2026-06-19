# ============================================================
#  hotspot/add_user.rsc — WIFIZONE
#  Crée un utilisateur hotspot
#  Injecté par l'agent : :local username/password/profile
# ============================================================

:local username "$username"
:local password "$password"
:local profile "$profile"

# Vérifier si l'utilisateur existe déjà
:local existing [/ip hotspot user find name=$username]
:if ([:len $existing] > 0) do={
    :put "USER_ALREADY_EXISTS"
    :error "Utilisateur existe deja"
}

# Créer l'utilisateur
/ip hotspot user add \
    name=$username \
    password=$password \
    profile=$profile \
    comment="WIFIZONE - cree le [/system clock get date]"

:put "USER_CREATED"
:put "username=$username"
:put "profile=$profile"
