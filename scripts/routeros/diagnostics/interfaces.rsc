# ============================================================
#  diagnostics/interfaces.rsc — WIFIZONE
#  Liste les interfaces réseau avec statut et trafic
# ============================================================

:put "=== INTERFACES ==="
:local count 0

:foreach iface in=[/interface find] do={
    :local name [/interface get $iface name]
    :local type [/interface get $iface type]
    :local running [/interface get $iface running]
    :local disabled [/interface get $iface disabled]
    :local comment [/interface get $iface comment]
    :local mac [/interface get $iface mac-address]
    :local mtu [/interface get $iface mtu]
    :local l2mtu [/interface get $iface l2mtu]

    :put ("name=" . $name . "|type=" . $type . "|running=" . $running . \
          "|disabled=" . $disabled . "|comment=" . $comment . \
          "|mac=" . $mac . "|mtu=" . $mtu . "|l2mtu=" . $l2mtu)
    :set count ($count + 1)
}

:put "=== END ==="
:put ("total=" . $count)
