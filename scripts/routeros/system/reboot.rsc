# ============================================================
#  system/reboot.rsc — WIFIZONE
#  Redémarre le routeur (action dangereuse)
#  L'agent vérifie le paramètre "confirm=true" AVANT l'appel
# ============================================================

:local confirm "$confirm"

:if ($confirm != "true") do={
    :put "REBOOT_REQUIRES_CONFIRM"
    :error "Envoyer confirm=true pour redemarrer"
}

:log warning "WIFIZONE - Redemarrage initie depuis l'agent"
:put "REBOOT_INITIATED"

# Attendre 2 secondes pour que la réponse SSH parte
:delay 2

/system reboot
