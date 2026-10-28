:local profileName "$profileName"
:local rateLimit "$rateLimit"
:local sharedUsers "$sharedUsers"
:local sessionTimeout "$sessionTimeout"
:local idleTimeout "$idleTimeout"
:local dataLimit "$dataLimit"

:if ($profileName = "") do={ :put "ERROR"; :error "profileName required" }

# Un profil RouterOS n'a pas de quota de donnees : il se pose sur l'utilisateur / le voucher.
# On refuse plutot que d'ignorer la valeur en silence.
:if ($dataLimit != "") do={
    :put "ERROR: data_limit n'existe pas au niveau du profil (a definir sur les utilisateurs/vouchers)"
    :error "data_limit unsupported"
}

# Vérifier si le profil existe (foreach + as-value car $name shadowé par propriété RouterOS)
:local exists 0
:foreach p in=[/ip hotspot user profile print as-value] do={
    :local pname ($p->"name")
    :if ($pname = $profileName) do={ :set exists 1 }
}

:if ($exists = 1) do={ :put "PROFILE_ALREADY_EXISTS"; :error "exists" }

# Créer avec add (le $profileName n'est pas shadowé ici)
/ip hotspot user profile add name=$profileName shared-users=$sharedUsers

:if ($rateLimit != "") do={ /ip hotspot user profile set [find name=$profileName] rate-limit=$rateLimit }
:if ($sessionTimeout != "") do={ /ip hotspot user profile set [find name=$profileName] session-timeout=$sessionTimeout }
:if ($idleTimeout != "") do={ /ip hotspot user profile set [find name=$profileName] idle-timeout=$idleTimeout }

:put "PROFILE_CREATED"
:put ("profile_name=" . $profileName)
:put ("rate_limit=" . $rateLimit)
:put ("session_timeout=" . $sessionTimeout)
:put ("idle_timeout=" . $idleTimeout)
