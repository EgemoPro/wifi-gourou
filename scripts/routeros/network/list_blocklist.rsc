# ============================================================
#  network/list_blocklist.rsc — WIFIZONE
#  Liste les address-lists firewall (blocklists)
#  Lecture seule — ne modifie rien
# ============================================================

:put "=== BLOCKLISTS ==="

:local totalEntries 0

:foreach list in=[/ip firewall address-list find] do={
    :local listName [/ip firewall address-list get $list list]
    :local listAddr [/ip firewall address-list get $list address]
    :local listTimeout [/ip firewall address-list get $list timeout]
    :local listDynamic [/ip firewall address-list get $list dynamic]

    :put ("list=" . $listName . "|address=" . $listAddr . \
          "|timeout=" . $listTimeout . "|dynamic=" . $listDynamic)
    :set totalEntries ($totalEntries + 1)
}

:put "=== END ==="
:put ("total_entries=" . $totalEntries)
