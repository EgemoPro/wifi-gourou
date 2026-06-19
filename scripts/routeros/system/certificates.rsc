# ============================================================
#  system/certificates.rsc — WIFIZONE
#  État des certificats SSL (lecture seule)
# ============================================================

:put "=== CERTIFICATES ==="
:local count 0

:do {
    :foreach c in=[/certificate print as-value] do={
        :local name ($c->"name")
        :local subject ($c->"subject")
        :local issuer ($c->"issuer")
        :local statusStr ($c->"status")
        :local daysValid ($c->"days-valid")
        :local daysRemaining ($c->"days-remaining")
        :local trusted ($c->"trusted")
        :local revoked ($c->"revoked")
        :local ca ($c->"ca")

        :if ($name = "") do={ :set name "-" }
        :if ($subject = "") do={ :set subject "-" }
        :if ($issuer = "") do={ :set issuer "-" }
        :if ($daysRemaining = "") do={ :set daysRemaining "?" }

        :put ("name=" . $name . "|subject=" . $subject . \
              "|issuer=" . $issuer . "|status=" . $statusStr . \
              "|days_valid=" . $daysValid . "|days_remaining=" . $daysRemaining . \
              "|trusted=" . $trusted . "|revoked=" . $revoked . \
              "|ca=" . $ca)
        :set count ($count + 1)
    }
} on-error={
    :put "certs_error=query_failed"
}

:put "=== END ==="
:put ("total=" . $count)
