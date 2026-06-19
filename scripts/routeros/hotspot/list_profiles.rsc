# ============================================================
#  hotspot/list_profiles.rsc — WIFIZONE
#  Liste tous les profils hotspot (as-value pattern)
# ============================================================

:put "=== PROFILES ==="
:local count 0

:do {
    :foreach p in=[/ip hotspot user profile print as-value] do={
        :local name ($p->"name")
        :local rateLimit ($p->"rate-limit")
        :local sharedUsers ($p->"shared-users")
        :local sessionTimeout ($p->"session-timeout")
        :local idleTimeout ($p->"idle-timeout")
        :local limitBytes ($p->"limit-bytes-total")
        :local addressPool ($p->"address-pool")

        :if ($rateLimit = "") do={ :set rateLimit "none" }
        :if ($limitBytes = "") do={ :set limitBytes "unlimited" }
        :if ($addressPool = "") do={ :set addressPool "none" }

        :put ("name=" . $name . "|rate_limit=" . $rateLimit . \
              "|shared_users=" . $sharedUsers . "|session_timeout=" . $sessionTimeout . \
              "|idle_timeout=" . $idleTimeout . "|limit_bytes=" . $limitBytes . \
              "|address_pool=" . $addressPool)
        :set count ($count + 1)
    }
} on-error={
    :put "profiles_error=query_failed"
}

:put "=== END ==="
:put ("total=" . $count)
