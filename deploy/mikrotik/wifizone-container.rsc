# =============================================================================
#  WIFIZONE - Agent + Tailscale en containers sur RouterOS 7
#
#  A FAIRE AVANT (voir deploy/mikrotik/README.md, etapes 1 a 4) :
#    - package "container" installe, device-mode container=yes confirme
#    - cle USB formatee ext4, fichiers wz-agent.tar et wz-tailscale.tar copies
#      dans <disk>/wifizone/
#
#  UTILISATION :
#    1. Editer la section PARAMETRES ci-dessous
#    2. /import file-name=wifizone-container.rsc
#
#  Le script peut etre relance : il ne recree pas ce qui existe deja.
#  Ne pas utiliser les caracteres   "   $   \   ?   dans les secrets.
# =============================================================================

# ------------------------------ PARAMETRES -----------------------------------
:local siteId        "SITE_A"
:local siteName      "WIFIZONE Site A"
:local tsHostname    "wz-site-a"
:local disk          "usb1"
:local netPrefix     "172.31.0"
:local cmdPort       "9001"
:local alertPort     "9000"
:local centralHost   "100.64.0.10"
:local centralPort   "5678"
:local centralApiKey "CHANGE_ME"
:local tsAuthKey     "CHANGE_ME"
:local agentUser     "api-agent"
:local agentPass     "CHANGE_ME"
:local agentTsAddr   ""
:local tz            "Africa/Niamey"
:local agentMemHigh  "200M"
:local tsMemHigh     "128M"
# -----------------------------------------------------------------------------

# Valeurs derivees
:local subnet ($netPrefix . ".0/24")
:local gwIp   ($netPrefix . ".1")
:local tsIp   ($netPrefix . ".2")
:local agIp   ($netPrefix . ".3")
:local base   ($disk . "/wifizone")
:if ([:len $agentTsAddr] = 0) do={ :set agentTsAddr $tsHostname }

# ------------------------------ VERIFICATIONS --------------------------------
:if (($tsAuthKey = "CHANGE_ME") || ($centralApiKey = "CHANGE_ME") || ($agentPass = "CHANGE_ME")) do={
    :error "WIFIZONE: renseigner tsAuthKey, centralApiKey et agentPass (section PARAMETRES)"
}

:local containerOk false
:do { /container print count-only; :set containerOk true } on-error={}
:if (!$containerOk) do={
    :error "WIFIZONE: menu /container indisponible (package container absent ?) - voir README etape 1"
}

:local dm "?"
:do { :set dm [/system device-mode get container] } on-error={}
:if ($dm = false) do={
    :error "WIFIZONE: device-mode container=no. Lancer /system device-mode update container=yes puis confirmer (bouton reset) - voir README etape 1"
}

:foreach f in={"wz-agent.tar";"wz-tailscale.tar"} do={
    :if ([:len [/file find where name=($base . "/" . $f)]] = 0) do={
        :error ("WIFIZONE: fichier manquant : " . $base . "/" . $f)
    }
}
:put "WIFIZONE: verifications OK"

# ------------------------------ RESEAU ---------------------------------------
:if ([:len [/interface bridge find where name="br-containers"]] = 0) do={
    /interface bridge add name=br-containers comment="WIFIZONE containers"
}
:if ([:len [/ip address find where interface="br-containers"]] = 0) do={
    /ip address add address=($gwIp . "/24") interface=br-containers comment="WIFIZONE containers"
}
:if ([:len [/interface veth find where name="veth-wz-ts"]] = 0) do={
    /interface veth add name=veth-wz-ts address=($tsIp . "/24") gateway=$gwIp comment="WIFIZONE tailscale"
}
:if ([:len [/interface veth find where name="veth-wz-agent"]] = 0) do={
    /interface veth add name=veth-wz-agent address=($agIp . "/24") gateway=$gwIp comment="WIFIZONE agent"
}
:foreach v in={"veth-wz-ts";"veth-wz-agent"} do={
    :if ([:len [/interface bridge port find where interface=$v]] = 0) do={
        /interface bridge port add bridge=br-containers interface=$v
    }
}

# Acces Internet des containers (Tailscale doit joindre ses serveurs)
:if ([:len [/ip firewall nat find where comment="WIFIZONE containers masquerade"]] = 0) do={
    /ip firewall nat add chain=srcnat action=masquerade src-address=$subnet comment="WIFIZONE containers masquerade"
}

# ------------------------------ PARE-FEU -------------------------------------
# Regle 1 : l'agent peut ouvrir SSH vers le routeur (et rien d'autre)
:local rule1 "WIFIZONE: agent vers SSH routeur"
:if ([:len [/ip firewall filter find where comment=$rule1]] = 0) do={
    :if ([:len [/ip firewall filter find]] > 0) do={
        /ip firewall filter add chain=input action=accept protocol=tcp dst-port=22 src-address=$agIp comment=$rule1 place-before=0
    } else={
        /ip firewall filter add chain=input action=accept protocol=tcp dst-port=22 src-address=$agIp comment=$rule1
    }
}

# Regle 2 : AUCUNE connexion nouvelle depuis les clients WiFi / le WAN vers les containers.
# Sans elle, un client du hotspot pourrait atteindre le proxy Tailscale (donc tout le tailnet).
:local rule2 "WIFIZONE: bloquer acces aux containers"
:if ([:len [/ip firewall filter find where comment=$rule2]] = 0) do={
    :if ([:len [/ip firewall filter find]] > 0) do={
        /ip firewall filter add chain=forward action=drop connection-state=new dst-address=$subnet comment=$rule2 place-before=0
    } else={
        /ip firewall filter add chain=forward action=drop connection-state=new dst-address=$subnet comment=$rule2
    }
}

# ------------------------------ UTILISATEUR AGENT ----------------------------
:do { /user group add name=$agentUser policy=read,write,api,ssh,password,test comment="WIFIZONE agent" } on-error={}
:if ([:len [/user find where name=$agentUser]] = 0) do={
    /user add name=$agentUser group=$agentUser password=$agentPass comment="WIFIZONE Agent - ne pas supprimer"
} else={
    /user set [/user find where name=$agentUser] password=$agentPass
}

# Avertissement si le service SSH est restreint par adresse (on ne le modifie pas)
:local sshAddr [:tostr [/ip service get ssh address]]
:if (([:len $sshAddr] > 0) && ([:typeof [:find $sshAddr $agIp]] = "nil")) do={
    :put ("WIFIZONE ATTENTION: /ip service ssh est restreint a : " . $sshAddr)
    :put ("   Ajouter " . $subnet . " a cette liste, sinon l'agent ne pourra pas se connecter.")
}

# ------------------------------ CONTAINERS : CONFIG --------------------------
:do { /container config set tmpdir=($base . "/tmp") } on-error={ :put "WIFIZONE: tmpdir non applique (ignore)" }

# Montages (volumes persistants sur la cle USB)
/container mounts remove [find where list="wz-ts-state"]
/container mounts remove [find where list="wz-agent-data"]
/container mounts add list=wz-ts-state src=($base . "/ts-state") dst=/var/lib/tailscale
/container mounts add list=wz-agent-data src=($base . "/agent-data") dst=/data

# Variables d'environnement - Tailscale
/container envs remove [find where list="wz-ts"]
/container envs add list=wz-ts key=TS_AUTHKEY value=$tsAuthKey
/container envs add list=wz-ts key=TS_HOSTNAME value=$tsHostname
/container envs add list=wz-ts key=TS_STATE_DIR value="/var/lib/tailscale"
/container envs add list=wz-ts key=TS_USERSPACE value="true"
/container envs add list=wz-ts key=TS_AUTH_ONCE value="true"
/container envs add list=wz-ts key=TS_SOCKS5_SERVER value=":1055"
/container envs add list=wz-ts key=WZ_FORWARD_PORT value=$cmdPort
/container envs add list=wz-ts key=WZ_FORWARD_TARGET value=($agIp . ":" . $cmdPort)

# Variables d'environnement - Agent
/container envs remove [find where list="wz-agent"]
/container envs add list=wz-agent key=SITE_ID value=$siteId
/container envs add list=wz-agent key=SITE_NAME value=$siteName
/container envs add list=wz-agent key=MIKROTIK_HOST value=$gwIp
/container envs add list=wz-agent key=MIKROTIK_USER value=$agentUser
/container envs add list=wz-agent key=MIKROTIK_PASSWORD value=$agentPass
/container envs add list=wz-agent key=CENTRAL_HOST value=$centralHost
/container envs add list=wz-agent key=CENTRAL_PORT value=$centralPort
/container envs add list=wz-agent key=CENTRAL_API_KEY value=$centralApiKey
/container envs add list=wz-agent key=AGENT_TAILSCALE_IP value=$agentTsAddr
/container envs add list=wz-agent key=COMMAND_PORT value=$cmdPort
/container envs add list=wz-agent key=ALERT_PORT value=$alertPort
/container envs add list=wz-agent key=ALL_PROXY value=("socks5h://" . $tsIp . ":1055")
/container envs add list=wz-agent key=NO_PROXY value=($subnet . ",127.0.0.1,localhost")
/container envs add list=wz-agent key=TZ value=$tz
/container envs add list=wz-agent key=DATA_DIR value="/data"
/container envs add list=wz-agent key=LOG_LEVEL value="INFO"

# ------------------------------ CONTAINERS : CREATION ------------------------
:if ([:len [/container find where name="wz-tailscale"]] = 0) do={
    /container add name=wz-tailscale file=($base . "/wz-tailscale.tar") interface=veth-wz-ts root-dir=($base . "/root-ts") envlist=wz-ts mountlists=wz-ts-state dns=1.1.1.1,8.8.8.8 logging=yes start-on-boot=yes comment="WIFIZONE tailscale"
}
:if ([:len [/container find where name="wz-agent"]] = 0) do={
    /container add name=wz-agent file=($base . "/wz-agent.tar") interface=veth-wz-agent root-dir=($base . "/root-agent") envlist=wz-agent mountlists=wz-agent-data dns=1.1.1.1,8.8.8.8 logging=yes start-on-boot=yes comment="WIFIZONE agent"
}

# ------------------------------ DEMARRAGE ------------------------------------
# L'extraction de l'image est asynchrone (plusieurs minutes sur une cle USB).
:foreach n in={"wz-tailscale";"wz-agent"} do={
    :local id [/container find where name=$n]
    :local tries 0
    :while (([/container get $id status] != "stopped") && ([/container get $id status] != "running") && ($tries < 150)) do={
        :delay 2s
        :set tries ($tries + 1)
    }
    :local mem $tsMemHigh
    :if ($n = "wz-agent") do={ :set mem $agentMemHigh }
    :do { /container set $id memory-high=$mem } on-error={ :put ("WIFIZONE: memory-high non supporte pour " . $n . " (ignore)") }
    :if ([/container get $id status] = "stopped") do={
        /container start $id
        :put ("WIFIZONE: " . $n . " demarre")
    }
}

# ------------------------------ SUITE ----------------------------------------
:put "=================== WIFIZONE ==================="
:put "Etat      : /container print"
:put "Journal   : /log print  (topic container)"
:put ("1) Verifier que la machine " . $tsHostname . " apparait dans la console Tailscale.")
:put "2) Si le central ne resout pas les noms MagicDNS, mettre l'IP 100.x de cette machine :"
:put "   /container envs set [find where list=wz-agent and key=AGENT_TAILSCALE_IP] value=100.x.x.x"
:put "   /container stop wz-agent   puis   /container start wz-agent"
:put "3) Tester depuis le central :  http://<IP 100.x ou nom>:9001/health"
