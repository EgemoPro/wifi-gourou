# ============================================================
#  hotspot/list_profiles.rsc — WIFIZONE
#  Liste tous les profils hotspot (attributs préfixés)
# ============================================================

:local count 0

:do {
    :foreach p in=[/ip hotspot user/profile print as-value] do={
        :local pName ($p->"name")
        :local pRateLimit ($p->"rate-limit")
        :local pSharedUsers ($p->"shared-users")
        :local pSessionTimeout ($p->"session-timeout")
        :local pIdleTimeout ($p->"idle-timeout")
        :local pLimitBytes ($p->"limit-bytes-total")
        :local pAddressPool ($p->"address-pool")

        :if ($pRateLimit = "") do={ :set pRateLimit "none" }
        :if ($pLimitBytes = "") do={ :set pLimitBytes "unlimited" }
        :if ($pAddressPool = "") do={ :set pAddressPool "none" }

        :put ("profile_" . $count . "_name=" . $pName)
        :put ("profile_" . $count . "_rate_limit=" . $pRateLimit)
        :put ("profile_" . $count . "_shared_users=" . $pSharedUsers)
        :put ("profile_" . $count . "_session_timeout=" . $pSessionTimeout)
        :put ("profile_" . $count . "_idle_timeout=" . $pIdleTimeout)
        :put ("profile_" . $count . "_limit_bytes=" . $pLimitBytes)
        :put ("profile_" . $count . "_address_pool=" . $pAddressPool)

        :set count ($count + 1)
    }
} on-error={
    :put "profiles_error=query_failed"
}

:put ("profiles_total=" . $count)
