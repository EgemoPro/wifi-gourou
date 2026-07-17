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

    :put ("int_" . $count . "_name=" . $name)
    :put ("int_" . $count . "_type=" . $type)
    :put ("int_" . $count . "_running=" . $running)
    :put ("int_" . $count . "_disabled=" . $disabled)
    :put ("int_" . $count . "_comment=" . $comment)
    :put ("int_" . $count . "_mac=" . $mac)
    :put ("int_" . $count . "_mtu=" . $mtu)
    :put ("int_" . $count . "_l2mtu=" . $l2mtu)
    :set count ($count + 1)
}

:put "=== END ==="
:put ("total=" . $count)
