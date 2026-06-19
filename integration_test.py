#!/usr/bin/env python3
"""
integration_test.py — Test complet du flux Agent ↔ n8n ↔ MikroTik
Simule les opérations de l'agent réel
"""

import sys
import time
import requests
import json
from config import CONFIG
from mikrotik import MikroTikPool
from collector import collect_metrics, collect_clients

print("="*70)
print("🧪 TEST INTÉGRATION COMPLET")
print("="*70)

# Configuration
N8N_HOST = "http://localhost:5678"
API_KEY = CONFIG.get("central_api_key")
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

test_results = {}

# ═══════════════════════════════════════════════════════════════════════════════
print("\n[ÉTAPE 1] Connexion MikroTik et collecte de données")
print("━" * 70)

try:
    pool = MikroTikPool(CONFIG)
    
    # Collecter métriques
    metrics = collect_metrics(pool, CONFIG)
    test_results["collect_metrics"] = "OK" if metrics else "FAIL"
    
    if metrics:
        print(f"✓ Métriques collectées :")
        print(f"  - CPU       : {metrics.cpu_load}%")
        print(f"  - Memory    : {metrics.memory_free} / {metrics.memory_total}")
        print(f"  - Users     : {metrics.active_users}")
        print(f"  - Uptime    : {metrics.uptime}")
    else:
        print(f"✗ Erreur collecte métriques")
    
    # Collecter clients
    clients = collect_clients(pool, CONFIG)
    test_results["collect_clients"] = "OK" if clients else "FAIL"
    
    if clients:
        print(f"✓ Clients collectés : {clients.count} client(s)")
    else:
        print(f"✗ Erreur collecte clients")
        
except Exception as e:
    print(f"✗ Erreur MikroTik : {e}")
    test_results["mikrotik"] = "FAIL"
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════════════════════
print("\n[ÉTAPE 2] Enregistrement du site auprès de n8n")
print("━" * 70)

try:
    payload = {
        "site_id": CONFIG.get("site_id"),
        "site_name": CONFIG.get("site_name"),
        "agent_url": f"http://{CONFIG.get('central_host')}:9001",
        "mikrotik_host": CONFIG.get("mikrotik_host"),
        "timestamp": "2026-06-13T12:00:00Z"
    }
    
    url = f"{N8N_HOST}/webhook/register"
    response = requests.post(url, json=payload, headers=HEADERS, timeout=5)
    
    if response.status_code in [200, 201]:
        print(f"✓ Enregistrement OK (HTTP {response.status_code})")
        print(f"  Response: {response.text[:100]}")
        test_results["webhook_register"] = "OK"
    elif response.status_code == 404:
        print(f"⚠️ HTTP 404 — Webhook /webhook/register non enregistré")
        print(f"  À corriger : Vérifier WF-REGISTER dans n8n")
        test_results["webhook_register"] = "MISSING_WEBHOOK"
    else:
        print(f"✗ HTTP {response.status_code}")
        test_results["webhook_register"] = "FAIL"
        
except Exception as e:
    print(f"✗ Erreur enregistrement : {e}")
    test_results["webhook_register"] = "ERROR"

# ═══════════════════════════════════════════════════════════════════════════════
print("\n[ÉTAPE 3] Envoi de métriques vers n8n")
print("━" * 70)

if metrics:
    try:
        payload = {
            "site_id": metrics.site_id,
            "site_name": metrics.site_name,
            "timestamp": metrics.timestamp,
            "cpu_load": metrics.cpu_load,
            "memory_free": metrics.memory_free,
            "memory_total": metrics.memory_total,
            "uptime": metrics.uptime,
            "ros_version": metrics.ros_version,
            "board_name": metrics.board_name,
            "active_users": metrics.active_users,
            "temperature": metrics.temperature
        }
        
        url = f"{N8N_HOST}/webhook/ingest-metrics"
        response = requests.post(url, json=payload, headers=HEADERS, timeout=5)
        
        if response.status_code in [200, 201]:
            print(f"✓ Métriques envoyées (HTTP {response.status_code})")
            print(f"  Response: {response.text[:100]}")
            test_results["webhook_metrics"] = "OK"
        elif response.status_code == 404:
            print(f"⚠️ HTTP 404 — Webhook /webhook/ingest-metrics non enregistré")
            test_results["webhook_metrics"] = "MISSING_WEBHOOK"
        else:
            print(f"✗ HTTP {response.status_code}")
            test_results["webhook_metrics"] = "FAIL"
            
    except Exception as e:
        print(f"✗ Erreur envoi métriques : {e}")
        test_results["webhook_metrics"] = "ERROR"

# ═══════════════════════════════════════════════════════════════════════════════
print("\n[ÉTAPE 4] Envoi des clients vers n8n")
print("━" * 70)

if clients:
    try:
        payload = {
            "site_id": clients.site_id,
            "site_name": clients.site_name,
            "timestamp": clients.timestamp,
            "count": clients.count,
            "clients": [
                {
                    "user": c.user,
                    "ip": c.ip,
                    "mac": c.mac,
                    "uptime": c.uptime,
                    "bytes_in": c.bytes_in,
                    "bytes_out": c.bytes_out,
                    "profile": c.profile
                }
                for c in clients.clients
            ]
        }
        
        url = f"{N8N_HOST}/webhook/ingest-clients"
        response = requests.post(url, json=payload, headers=HEADERS, timeout=5)
        
        if response.status_code in [200, 201]:
            print(f"✓ Clients envoyés (HTTP {response.status_code})")
            print(f"  Response: {response.text[:100]}")
            test_results["webhook_clients"] = "OK"
        elif response.status_code == 404:
            print(f"⚠️ HTTP 404 — Webhook /webhook/ingest-clients non enregistré")
            test_results["webhook_clients"] = "MISSING_WEBHOOK"
        else:
            print(f"✗ HTTP {response.status_code}")
            test_results["webhook_clients"] = "FAIL"
            
    except Exception as e:
        print(f"✗ Erreur envoi clients : {e}")
        test_results["webhook_clients"] = "ERROR"

# ═══════════════════════════════════════════════════════════════════════════════
print("\n[ÉTAPE 5] Envoi d'une alerte test")
print("━" * 70)

try:
    payload = {
        "site_id": CONFIG.get("site_id"),
        "site_name": CONFIG.get("site_name"),
        "timestamp": "2026-06-13T12:00:00Z",
        "alert_type": "CPU_HIGH",
        "message": "TEST: CPU load dépassé 80%",
        "data": {
            "cpu_load": 85.5,
            "threshold": 80
        }
    }
    
    url = f"{N8N_HOST}/webhook/ingest-alert"
    response = requests.post(url, json=payload, headers=HEADERS, timeout=5)
    
    if response.status_code in [200, 201]:
        print(f"✓ Alerte envoyée (HTTP {response.status_code})")
        print(f"  Response: {response.text[:100]}")
        test_results["webhook_alert"] = "OK"
    elif response.status_code == 404:
        print(f"⚠️ HTTP 404 — Webhook /webhook/ingest-alert non enregistré")
        test_results["webhook_alert"] = "MISSING_WEBHOOK"
    else:
        print(f"✗ HTTP {response.status_code}")
        test_results["webhook_alert"] = "FAIL"
        
except Exception as e:
    print(f"✗ Erreur envoi alerte : {e}")
    test_results["webhook_alert"] = "ERROR"

# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("📊 RÉSUMÉ DES TESTS")
print("="*70 + "\n")

for test, result in test_results.items():
    if result == "OK":
        symbol = "🟢"
    elif result == "MISSING_WEBHOOK":
        symbol = "🟡"
    else:
        symbol = "🔴"
    print(f"{symbol} {test:30} : {result}")

# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("✅ CONCLUSION")
print("="*70 + "\n")

ok_count = sum(1 for r in test_results.values() if r == "OK")
fail_count = sum(1 for r in test_results.values() if r == "FAIL" or r == "ERROR")
missing_count = sum(1 for r in test_results.values() if r == "MISSING_WEBHOOK")

print(f"✓ Réussis       : {ok_count}")
print(f"⚠️ Webhooks manquants : {missing_count}")
print(f"✗ Erreurs       : {fail_count}")

if fail_count == 0 and missing_count == 0:
    print("\n🚀 TOUS LES TESTS SONT PASSÉS !")
    print("L'agent peut être lancé : make run")
elif fail_count == 0:
    print("\n🟡 CONFIGURATION n8n INCOMPLÈTE")
    print("À faire : Configurer les webhooks manquants dans n8n")
    print("Voir RAPPORT_WEBHOOKS.md pour les détails")
else:
    print("\n🔴 ERREURS DÉTECTÉES")
    print("Consultez les messages d'erreur ci-dessus")

EOF
