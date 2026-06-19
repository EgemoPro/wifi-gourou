# ============================================================
#  WIFIZONE — Script MikroTik CLI (version corrigée)
# ============================================================

:local agentIP   "172.22.77.24"
:local agentPass "wifibatimentGHmedecin"

# Services # address=$agentIP
/ip service set api  disabled=no port=8728 
/ip service set ssh  disabled=no port=22   address=$agentIP
/ip service set telnet  disabled=yes
/ip service set ftp     disabled=yes
/ip service set api-ssl disabled=yes


# Utilisateur agent (ignore l'erreur si groupe existe déjà)
:do { /user group add name=api-agent \
    policy=read,write,api,ssh,password,test } on-error={}
:do { /user add name=api-agent group=api-agent \
    password=$agentPass \
    comment="WIFIZONE Agent - ne pas supprimer" } on-error={}

# Firewall SANS place-before=0
# /ip firewall filter add chain=input protocol=tcp dst-port=8728 \
#    src-address=!$agentIP action=drop \
#    comment="WIFIZONE - Bloquer API sauf agent"

# /ip firewall filter add chain=input protocol=tcp dst-port=22 \
#    src-address=!$agentIP action=drop \
#    comment="WIFIZONE - Bloquer SSH sauf agent"

# Vérification
:log info "WIFIZONE Agent - Configuration terminee"
:put "=== Services actifs ==="
/ip service print where disabled=no
:put "=== Utilisateur agent ==="
/user print where name=api-agent
:put "Configuration OK - Agent IP: $agentIP"
