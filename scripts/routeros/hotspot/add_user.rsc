# ============================================================
#  hotspot/add_user.rsc — WIFIZONE
#  Crée un utilisateur hotspot (avec limites optionnelles)
#  Injecté par l'agent : :local username/password/profile/
#                         comment/dataLimit/timeLimit
# ============================================================

# Note : les variables username/password/profile/comment/dataLimit/timeLimit
# sont injectées par l'agent via :local déclarations préfixées AVANT le script.
# Ne PAS re-déclarer ici — RouterOS v7 réinitialise la variable si on fait
#   :local var "$var"   ( $var déjà déclarée → devient vide )
# Valeurs par défaut si exécution standalone (sans l'agent)
:if ([:typeof $username] = "nothing") do={ :local username "" }
:if ([:typeof $password] = "nothing") do={ :local password "" }
:if ([:typeof $profile] = "nothing") do={ :local profile "default" }
:if ([:typeof $comment] = "nothing") do={ :local comment "" }
:if ([:typeof $dataLimit] = "nothing") do={ :local dataLimit "" }
:if ([:typeof $timeLimit] = "nothing") do={ :local timeLimit "" }

# Vérifier si l'utilisateur existe déjà
:local existing [/ip hotspot user find name=$username]
:if ([:len $existing] > 0) do={
    :put "USER_ALREADY_EXISTS"
    :error "Utilisateur existe deja"
}

# Construire le commentaire :
#   - Si déjà "vc:..." → utiliser tel quel (vouchers avec expiration)
#   - Si vide           → date par défaut
#   - Sinon             → préfixé WIFIZONE
:local dateStr [/system clock get date]
:local vcPrefix [:pick $comment 0 2]
:if ($comment = "") do={
    :set comment ("WIFIZONE - cree le " . $dateStr)
} else={
    :if ($vcPrefix = "vc") do={
        :set comment $comment
    } else={
        :set comment ("WIFIZONE - " . $comment . " - " . $dateStr)
    }
}

# Créer l'utilisateur avec les 4 champs principaux
/ip hotspot user add \
    name=$username \
    password=$password \
    profile=$profile \
    comment=$comment

# Appliquer les limites si fournies
:if ($dataLimit != "") do={
    /ip hotspot user set [find name=$username] limit-bytes-total=$dataLimit
    :put ("limit_bytes=" . $dataLimit)
}

:if ($timeLimit != "") do={
    /ip hotspot user set [find name=$username] limit-uptime=$timeLimit
    :put ("limit_uptime=" . $timeLimit)
}

:put "USER_CREATED"
:put "username=$username"
:put "profile=$profile"
