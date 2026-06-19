:local profileName "$profileName"
:local rateLimit "$rateLimit"
:local sharedUsers "$sharedUsers"
:local sessionTimeout "$sessionTimeout"
:local idleTimeout "$idleTimeout"
:local dataLimit "$dataLimit"

:if ($profileName = "") do={ :put "ERROR"; :error "profileName required" }

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

:put "PROFILE_CREATED"
:put ("profile_name=" . $profileName)
:put ("rate_limit=" . $rateLimit)
