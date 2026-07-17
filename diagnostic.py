#!/usr/bin/env python3
"""Diagnostic complet de l'agent WIFIZONE."""
import sys, json, time, urllib.request, urllib.error

BASE = "http://localhost:9001"
KEY = "daabc4e0ba3d529f2f4efbf750073f9f"
HEADERS = {
    "X-API-Key": KEY,
    "Content-Type": "application/json",
}
TIMEOUT = 30

ok = fail = 0

def api(path, data=None):
    url = f"{BASE}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=HEADERS, method="POST" if data else "GET")
    try:
        resp = urllib.request.urlopen(req, timeout=TIMEOUT)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code}
    except Exception as e:
        return {"_error": str(e)}

def test(label, path, data=None, expected_status="success"):
    global ok, fail
    r = api(path, data)
    if r.get("status") == expected_status:
        ms = r.get("execution_time_ms", "?")
        print(f"  ✅ {label:<30} {ms:>6}ms")
        ok += 1
    elif "_http_error" in r:
        print(f"  ❌ {label:<30} HTTP {r['_http_error']}")
        fail += 1
    elif "_error" in r:
        print(f"  ❌ {label:<30} {r['_error'][:50]}")
        fail += 1
    else:
        err = r.get("error", {})
        if isinstance(err, dict):
            msg = f"{err.get('type','?')}: {err.get('message','')[:60]}"
        else:
            msg = str(err)[:60]
        print(f"  ❌ {label:<30} {msg}")
        fail += 1

print()
print("╔══════════════════════════════════════════════════════╗")
print("║   DIAGNOSTIC GLOBAL — WIFIZONE AGENT v2             ║")
print("╚══════════════════════════════════════════════════════╝")
print()

# ── 1. Infrastructure ──
print("── 1. INFRASTRUCTURE ──")
h = api("/health")
print(f"  health    : status={h.get('status')}  version=v{h.get('version','?')}  site={h.get('site_id')}")
print(f"  queue     : pending={h.get('queue',{}).get('durable',{}).get('pending','?')}  dead={h.get('queue',{}).get('durable',{}).get('dead','?')}")
print(f"  storage   : commands={h.get('storage',{}).get('commands',{}).get('total',0)}")

c = api("/capabilities")
actions_count = len(c.get("capabilities", {}).get("actions", {}))
print(f"  actions   : {actions_count} disponibles")

a = api("/actions")
print(f"  actions   : {len(a.get('actions',{}))} listées")

# ── 2. Router ──
print("\n── 2. ROUTER ──")
test("router.health",       "/action", {"action": "router.health"})
test("router.info",         "/action", {"action": "router.info"})
test("router.backup",       "/action", {"action": "router.backup"})
test("system.uptime",       "/action", {"action": "system.uptime"})

# ── 3. Réseau ──
print("\n── 3. RÉSEAU ──")
test("network.interfaces",  "/action", {"action": "network.interfaces"})
test("network.dhcp_leases", "/action", {"action": "network.dhcp_leases"})
test("network.wan_info",    "/action", {"action": "network.wan_info"})
test("network.neighbors",   "/action", {"action": "network.neighbors"})

# ── 4. Système ──
print("\n── 4. SYSTÈME ──")
test("system.logs",          "/action", {"action": "system.logs", "payload": {"lines": 3}})
test("system.scheduler_list","/action", {"action": "system.scheduler_list"})
test("system.firmware",      "/action", {"action": "system.firmware"})
test("system.certificates",  "/action", {"action": "system.certificates"})

# ── 5. Profils ──
print("\n── 5. PROFILS HOTSPOT (CRUD) ──")
test("profile.list",         "/action", {"action": "profile.list"})
test("profile.create",       "/action", {"action": "profile.create", "payload": {"profileName": "diag-final", "rate_limit": "5M"}})
test("profile.update",       "/action", {"action": "profile.update", "payload": {"name": "diag-final", "rate_limit": "10M"}})
test("profile.delete",       "/action", {"action": "profile.delete", "payload": {"profileName": "diag-final"}})

# ── 6. Utilisateurs ──
print("\n── 6. UTILISATEURS HOTSPOT (CRUD) ──")
test("hotspot.list_active",  "/action", {"action": "hotspot.list_active"})
test("hotspot.create_user",  "/action", {"action": "hotspot.create_user", "payload": {"username": "diag-u", "password": "pass123", "profile": "1M-Limit"}})
test("hotspot.disable_user", "/action", {"action": "hotspot.disable_user", "payload": {"username": "diag-u"}})
test("hotspot.enable_user",  "/action", {"action": "hotspot.enable_user", "payload": {"username": "diag-u"}})
test("hotspot.delete_user",  "/action", {"action": "hotspot.delete_user", "payload": {"username": "diag-u"}})

# ── 7. Vouchers ──
print("\n── 7. VOUCHERS ──")
test("hotspot.vouchers",     "/action", {"action": "hotspot.vouchers", "payload": {"qty": "3", "profile": "default"}})
test("export_pdf",           "/action", {"action": "export_pdf", "payload": {"vouchers": '[{"code":"DIAG","profile":"default"}]', "filename": "diag-final.pdf"}})

# ── 8. Endurance ──
print("\n── 8. ENDURANCE (10x health checks) ──")
times = []
for i in range(10):
    t0 = time.time()
    r = api("/health")
    dt = int((time.time() - t0) * 1000)
    times.append(dt)
    print(f"  #{i+1} → {r.get('status','?')}  ({dt}ms)", end="")
    if r.get("status") == "ok":
        ok += 1
    else:
        fail += 1
        print(" ❌", end="")
    print()
avg = sum(times) / len(times)
print(f"  moyenne: {avg:.0f}ms  /  min: {min(times)}ms  /  max: {max(times)}ms")

# ── Résumé ──
print()
print("╔══════════════════════════════════════════════════════╗")
print(f"║   RÉSULTATS :  {ok:>2} succès  /  {fail:>2} échecs                 ║")
print("╚══════════════════════════════════════════════════════╝")
print()
print(f"Agent PID: {h.get('site_id')} — uptime depuis démarrage agent")
print(f"URL: {BASE}/health")

if fail > 0:
    print("\n⚠️  Des tests ont échoué — voir les ❌ ci-dessus")
    sys.exit(1)
else:
    print("\n✅ Tous les diagnostics sont passés")
