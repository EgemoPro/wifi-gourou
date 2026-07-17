# ============================================================
#  hotspot/setup_profile.rsc — WIFIZONE
#  Configure le on-login script d'un profile hotspot.
#  Injecté par l'agent : :local profileName/loginScript
# ============================================================

:local profileName "$profileName"
:local loginScript "$loginScript"

# Vérifier que le profile existe
:local existing [/ip hotspot user profile find name=$profileName]
:if ([:len $existing] = 0) do={
    :put "ERROR: Profile not found"
    :error "Profile not found"
}

# Injecter le on-login script
/ip hotspot user profile set [find name=$profileName] on-login=$loginScript

:put "ON_LOGIN_SET"
:put "DONE"
