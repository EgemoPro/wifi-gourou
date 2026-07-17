# ============================================================
#  hotspot/delete_profile.rsc — WIFIZONE
#  Supprime un profil hotspot + ses utilisateurs associés
#  + le scheduler cleanup correspondant
# ============================================================

:local profileName "$profileName"

:if ($profileName = "") do={ :put "ERROR"; :error "profileName required" }

# Vérifier si le profil existe
:local exists 0
:foreach p in=[/ip hotspot user profile print as-value] do={
    :local pname ($p->"name")
    :if ($pname = $profileName) do={ :set exists 1 }
}

:if ($exists = 0) do={ :put "PROFILE_NOT_FOUND"; :error "not found" }

# Supprimer les utilisateurs associés
:local users [/ip hotspot user find where profile=$profileName]
:if ([:len $users] > 0) do={
    :local count 0
    :foreach u in=$users do={ /ip hotspot user remove $u; :set count ($count + 1) }
    :put ("removed_users=" . $count)
}

# Supprimer le scheduler cleanup associé
:local cleanupName ("wf-cleanup-" . $profileName)
:local sched [/system scheduler find name=$cleanupName]
:if ([:len $sched] > 0) do={
    /system scheduler remove $sched
    :put ("removed_scheduler=" . $cleanupName)
}

# Supprimer le profil
/ip hotspot user profile remove [find name=$profileName]

:put "PROFILE_DELETED"
:put ("profile_name=" . $profileName)
