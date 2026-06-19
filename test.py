#!/usr/bin/env python3
"""
Test script pour vérifier la configuration de WIFIZONE Agent
Teste : Tailscale, MikroTik, PC Central, Nginx
"""

import os
import sys
import socket
import subprocess
import json
from pathlib import Path
from typing import Tuple, Optional

# Ajouter le répertoire courant au path
sys.path.insert(0, str(Path(__file__).parent))

try:
    from config import CONFIG
except ImportError:
    print("✗ Erreur : impossible de charger config.py")
    print("  Assurez-vous que le .env est configuré correctement")
    sys.exit(1)


def print_header(text: str) -> None:
    """Affiche un titre"""
    print(f"\n{'='*70}")
    print(f"  {text}")
    print(f"{'='*70}\n")


def print_section(text: str) -> None:
    """Affiche une section"""
    print(f"\n{text}")
    print("-" * 70)


def test_socket(host: str, port: int, timeout: int = 3) -> Tuple[bool, str]:
    """Test la connectivité socket"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        
        if result == 0:
            return True, "✓ Accessible"
        else:
            return False, f"✗ Connexion refusée ({result})"
    except socket.timeout:
        return False, "✗ Timeout"
    except socket.gaierror:
        return False, "✗ Hôte non trouvé"
    except Exception as e:
        return False, f"✗ Erreur : {e}"


def test_tailscale() -> bool:
    """Teste la présence et l'activation de Tailscale"""
    print_section("🌐 Test Tailscale")
    
    try:
        output = subprocess.check_output(["tailscale", "status"], text=True, timeout=5)
        
        # Chercher une adresse IP Tailscale
        for line in output.split("\n"):
            if "100." in line and "active" in line.lower():
                print(f"✓ Tailscale actif")
                print(f"  {line.strip()}")
                return True
        
        print("⚠ Tailscale installé mais pas d'adresse active")
        return False
        
    except FileNotFoundError:
        print("✗ Tailscale non installé")
        return False
    except Exception as e:
        print(f"✗ Erreur : {e}")
        return False


def test_mikrotik() -> bool:
    """Teste la connexion au MikroTik local"""
    print_section("🔧 Test MikroTik")
    
    host = CONFIG.get("mikrotik_host")
    port = CONFIG.get("mikrotik_port")
    user = CONFIG.get("mikrotik_user")
    password = CONFIG.get("mikrotik_password")
    
    print(f"Cible   : {host}:{port}")
    print(f"User    : {user}")
    
    # Test socket d'abord
    ok, msg = test_socket(host, port)
    print(f"Socket  : {msg}")
    
    if not ok:
        return False
    
    # Test API
    try:
        from mikrotik import MikroTikPool
        
        pool = MikroTikPool(CONFIG)
        result = pool.execute("/system/identity", "print")
        
        print(f"✓ Connecté à MikroTik")
        if result and len(result) > 0:
            print(f"  Identité : {result[0].get('name', 'N/A')}")
        
        return True
        
    except Exception as e:
        print(f"✗ Erreur API : {e}")
        return False


def test_central() -> bool:
    """Teste la connexion au PC Central"""
    print_section("🖥️  Test PC Central (n8n)")
    
    host = CONFIG.get("central_host")
    port = CONFIG.get("central_port")
    api_key = CONFIG.get("central_api_key", "")
    
    print(f"Cible   : {host}:{port}")
    print(f"API Key : {api_key[:20]}..." if len(api_key) > 20 else f"API Key : {api_key}")
    
    # Test socket
    ok, msg = test_socket(host, port)
    print(f"Socket  : {msg}")
    
    if not ok:
        return False
    
    # Test HTTP
    try:
        import requests
        
        headers = {"X-API-Key": api_key}
        url = f"http://{host}:{port}/webhook/test"
        
        response = requests.get(url, headers=headers, timeout=3)
        
        if response.status_code in [200, 404, 405]:
            print(f"✓ n8n répond (HTTP {response.status_code})")
            return True
        elif response.status_code == 401:
            print(f"✗ Authentification échouée (HTTP 401)")
            print(f"  Vérifiez CENTRAL_API_KEY")
            return False
        else:
            print(f"⚠ Réponse inattendue (HTTP {response.status_code})")
            return True
        
    except Exception as e:
        print(f"✗ Erreur HTTP : {e}")
        return False



def test_environment() -> bool:
    """Teste que toutes les variables obligatoires sont configurées"""
    print_section("⚙️  Variables de configuration")
    
    required = [
        "site_id",
        "site_name",
        "mikrotik_host",
        "mikrotik_password",
        "central_host",
        "central_api_key",
    ]
    
    all_ok = True
    for var in required:
        value = CONFIG.get(var, "")
        if value:
            if "password" in var.lower() or "key" in var.lower():
                display = f"{value[:20]}..."
            else:
                display = value
            print(f"✓ {var:30} = {display}")
        else:
            print(f"✗ {var:30} = (MANQUANT)")
            all_ok = False
    
    return all_ok


def main():
    print_header("🔍 WIFIZONE Agent — Tests de configuration")
    
    results = {}
    
    # Test 1 : Variables
    results["Variables"] = test_environment()
    
    if not results["Variables"]:
        print("\n" + "="*70)
        print("✗ Configuration incomplète")
        print("  Exécutez : python setup.py")
        sys.exit(1)
    
    # Test 2 : Tailscale
    results["Tailscale"] = test_tailscale()
    
    # Test 3 : MikroTik
    results["MikroTik"] = test_mikrotik()
    
    # Test 4 : PC Central
    results["PC Central"] = test_central()
    
    # Test 5 : PC Central (déjà fait)
    
    # Résumé
    print_header("📊 Résumé des tests")
    
    for name, ok in results.items():
        status = "✓ OK" if ok else "✗ ERREUR"
        print(f"{status:8} {name}")
    
    all_ok = all(results.values())
    
    print("\n" + "="*70)
    
    if all_ok:
        print("✓ Tous les tests sont passés !")
        print("  Vous pouvez maintenant démarrer l'agent : python main.py")
    else:
        print("✗ Certains tests ont échoué")
        print("  Vérifiez les messages d'erreur ci-dessus")
        print("  Re-lancer : python test.py")
    
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n✗ Tests interrompus")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Erreur fatale : {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
