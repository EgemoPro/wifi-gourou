#!/usr/bin/env python3
"""
Configuration setup script pour WIFIZONE Agent
Aide l'utilisateur à remplir le fichier .env avec les bonnes valeurs.
"""

import os
import sys
import subprocess
from pathlib import Path
from typing import Optional

AGENT_DIR = Path(__file__).parent
ENV_FILE = AGENT_DIR / ".env"
ENV_TEMPLATE = AGENT_DIR / ".env.site_a"


def print_header(text: str) -> None:
    """Affiche un titre formaté"""
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")


def print_step(step: int, text: str) -> None:
    """Affiche une étape numérotée"""
    print(f"\n[{step}] {text}")
    print("-" * 60)


def get_input(prompt: str, default: Optional[str] = None) -> str:
    """Demande une entrée utilisateur avec valeur par défaut"""
    if default:
        display = f"{prompt} [{default}]: "
    else:
        display = f"{prompt}: "
    
    value = input(display).strip()
    return value if value else default or ""


def test_tailscale_ip() -> Optional[str]:
    """Détecte automatiquement l'IP Tailscale"""
    try:
        output = subprocess.check_output(["tailscale", "status"], text=True)
        for line in output.split("\n"):
            if "100.64" in line or "100.65" in line:
                parts = line.split()
                if parts:
                    return parts[0]
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return None


def test_connectivity(host: str, port: int) -> bool:
    """Test la connectivité vers un hôte:port"""
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def read_env_file() -> dict:
    """Lit le fichier .env existant"""
    config = {}
    if ENV_FILE.exists():
        with open(ENV_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if "=" in line:
                        key, value = line.split("=", 1)
                        config[key.strip()] = value.strip()
    return config


def write_env_file(config: dict) -> None:
    """Écrit le fichier .env"""
    with open(ENV_FILE, "w") as f:
        f.write("# WIFIZONE Agent — Configuration générée\n")
        f.write("# Généré par setup.py\n\n")
        
        # Variables obligatoires d'abord
        required = ["SITE_ID", "SITE_NAME", "MIKROTIK_HOST", "MIKROTIK_PASSWORD",
                   "CENTRAL_HOST", "CENTRAL_API_KEY"]
        optional = [k for k in config.keys() if k not in required]
        
        for key in required:
            if key in config:
                f.write(f"{key}={config[key]}\n")
        
        f.write("\n# Paramètres optionnels\n")
        for key in sorted(optional):
            f.write(f"{key}={config[key]}\n")
    
    print(f"✓ Fichier .env écrit : {ENV_FILE}")


def main():
    print_header("🔧 WIFIZONE Agent — Setup Interactif")
    
    # Lire la config existante
    existing_config = read_env_file()
    
    config = {}
    
    # ════════════════════════════════════════════════════════════════════════
    print_step(1, "Identité du site")
    print("(Utilisez des codes courts : SITE_A, SITE_B, etc)")
    
    config["SITE_ID"] = get_input(
        "Code du site",
        existing_config.get("SITE_ID", "SITE_A")
    )
    config["SITE_NAME"] = get_input(
        "Nom du site",
        existing_config.get("SITE_NAME", "WIFIZONE Plateau")
    )
    
    # ════════════════════════════════════════════════════════════════════════
    print_step(2, "Configuration MikroTik local")
    print("(Les adresses IP doivent être accessibles depuis ce PC)")
    
    config["MIKROTIK_HOST"] = get_input(
        "IP du MikroTik",
        existing_config.get("MIKROTIK_HOST", "192.168.10.1")
    )
    
    # Test de connectivity
    if test_connectivity(config["MIKROTIK_HOST"], 8728):
        print(f"✓ MikroTik sur {config['MIKROTIK_HOST']}:8728 → Accessible")
    else:
        print(f"⚠ MikroTik sur {config['MIKROTIK_HOST']}:8728 → Pas accessible")
        print("  Vérifiez l'adresse IP et la connectivité")
    
    config["MIKROTIK_PORT"] = get_input(
        "Port API MikroTik",
        existing_config.get("MIKROTIK_PORT", "8728")
    )
    
    config["MIKROTIK_USER"] = get_input(
        "Utilisateur API MikroTik",
        existing_config.get("MIKROTIK_USER", "api-agent")
    )
    
    config["MIKROTIK_PASSWORD"] = get_input(
        "Mot de passe utilisateur API",
        existing_config.get("MIKROTIK_PASSWORD", "")
    )
    
    if not config["MIKROTIK_PASSWORD"]:
        print("⚠ Le mot de passe est OBLIGATOIRE")
        sys.exit(1)
    
    config["MIKROTIK_SSH_PORT"] = get_input(
        "Port SSH MikroTik",
        existing_config.get("MIKROTIK_SSH_PORT", "22")
    )
    
    config["MIKROTIK_ROS_VERSION"] = get_input(
        "Version RouterOS (6 ou 7)",
        existing_config.get("MIKROTIK_ROS_VERSION", "7")
    )
    
    # ════════════════════════════════════════════════════════════════════════
    print_step(3, "Configuration PC Central (via Tailscale)")
    print("(Le PC Central doit être joignable via Tailscale)")
    
    # Détecter IP Tailscale
    tailscale_ip = test_tailscale_ip()
    if tailscale_ip:
        print(f"ℹ IP Tailscale détectée : {tailscale_ip}")
    
    config["CENTRAL_HOST"] = get_input(
        "IP Tailscale PC Central",
        existing_config.get("CENTRAL_HOST", tailscale_ip or "100.64.0.1")
    )
    
    # Test de connectivity
    if test_connectivity(config["CENTRAL_HOST"], 5678):
        print(f"✓ n8n sur {config['CENTRAL_HOST']}:5678 → Accessible")
    else:
        print(f"⚠ n8n sur {config['CENTRAL_HOST']}:5678 → Pas accessible")
        print("  Vérifiez que Tailscale est actif et l'IP correcte")
    
    config["CENTRAL_PORT"] = get_input(
        "Port n8n",
        existing_config.get("CENTRAL_PORT", "5678")
    )
    
    config["CENTRAL_API_KEY"] = get_input(
        "Clé d'authentification n8n (32 caractères)",
        existing_config.get("CENTRAL_API_KEY", "")
    )
    
    if not config["CENTRAL_API_KEY"]:
        print("⚠ La clé API est OBLIGATOIRE")
        print("  Vous la trouverez dans les variables globales n8n")
        sys.exit(1)
    
    if len(config["CENTRAL_API_KEY"]) < 30:
        print(f"⚠ La clé semble trop courte ({len(config['CENTRAL_API_KEY'])} char)")
    
    # ════════════════════════════════════════════════════════════════════════
    print_step(4, "Configuration Tailscale (optionnel)")
    print("(L'IP sera auto-détectée si vous laissez vide)")
    
    config["AGENT_TAILSCALE_IP"] = get_input(
        "IP Tailscale de cet agent",
        existing_config.get("AGENT_TAILSCALE_IP", "")
    )
    
    # ════════════════════════════════════════════════════════════════════════
    print_step(5, "Ports de l'agent (par défaut OK)")
    
    config["ALERT_PORT"] = get_input(
        "Port alerte",
        existing_config.get("ALERT_PORT", "9000")
    )
    
    config["COMMAND_PORT"] = get_input(
        "Port commande",
        existing_config.get("COMMAND_PORT", "9001")
    )
    
    # ════════════════════════════════════════════════════════════════════════
    print_step(6, "Intervalles de collection (en secondes, par défaut OK)")
    
    config["INTERVAL_METRICS"] = get_input(
        "Métriques",
        existing_config.get("INTERVAL_METRICS", "300")
    )
    
    config["INTERVAL_CLIENTS"] = get_input(
        "Clients connectés",
        existing_config.get("INTERVAL_CLIENTS", "60")
    )
    
    config["INTERVAL_BANDWIDTH"] = get_input(
        "Vérif débit",
        existing_config.get("INTERVAL_BANDWIDTH", "120")
    )
    
    config["INTERVAL_OFFLINE"] = get_input(
        "Vérif MikroTik online",
        existing_config.get("INTERVAL_OFFLINE", "120")
    )
    
    config["INTERVAL_USER_BLOAT"] = get_input(
        "Surcharge users",
        existing_config.get("INTERVAL_USER_BLOAT", "3600")
    )
    
    config["INTERVAL_SCHEDULERS"] = get_input(
        "Vérif scheduleurs",
        existing_config.get("INTERVAL_SCHEDULERS", "3600")
    )
    
    config["BACKUP_HOUR"] = get_input(
        "Heure backup (0-23)",
        existing_config.get("BACKUP_HOUR", "2")
    )
    
    config["REGISTER_RETRY"] = get_input(
        "Retry enregistrement",
        existing_config.get("REGISTER_RETRY", "60")
    )
    
    # ════════════════════════════════════════════════════════════════════════
    print_step(7, "Seuils d'alertes (par défaut OK)")
    
    config["THRESHOLD_CPU"] = get_input(
        "Seuil CPU (%)",
        existing_config.get("THRESHOLD_CPU", "80")
    )
    
    config["THRESHOLD_CPU_CYCLES"] = get_input(
        "Cycles avant alerte CPU",
        existing_config.get("THRESHOLD_CPU_CYCLES", "2")
    )
    
    config["THRESHOLD_BANDWIDTH_MB"] = get_input(
        "Débit suspect (MB)",
        existing_config.get("THRESHOLD_BANDWIDTH_MB", "500")
    )
    
    config["THRESHOLD_MAX_USERS"] = get_input(
        "Seuil warn users",
        existing_config.get("THRESHOLD_MAX_USERS", "200")
    )
    
    config["THRESHOLD_MAX_SCHEDULERS"] = get_input(
        "Seuil warn scheduleurs",
        existing_config.get("THRESHOLD_MAX_SCHEDULERS", "20")
    )
    
    config["THRESHOLD_OFFLINE_RETRIES"] = get_input(
        "Retries avant offline",
        existing_config.get("THRESHOLD_OFFLINE_RETRIES", "3")
    )
    
    # ════════════════════════════════════════════════════════════════════════
    print_header("📋 Résumé de la configuration")
    
    print("Identité du site :")
    print(f"  SITE_ID             = {config['SITE_ID']}")
    print(f"  SITE_NAME           = {config['SITE_NAME']}")
    
    print("\nMikroTik local :")
    print(f"  MIKROTIK_HOST       = {config['MIKROTIK_HOST']}")
    print(f"  MIKROTIK_USER       = {config['MIKROTIK_USER']}")
    print(f"  MIKROTIK_PORT       = {config['MIKROTIK_PORT']}")
    print(f"  MIKROTIK_SSH_PORT   = {config['MIKROTIK_SSH_PORT']}")
    print(f"  MIKROTIK_ROS_VERSION= {config['MIKROTIK_ROS_VERSION']}")
    
    print("\nPC Central :")
    print(f"  CENTRAL_HOST        = {config['CENTRAL_HOST']}")
    print(f"  CENTRAL_PORT        = {config['CENTRAL_PORT']}")
    print(f"  CENTRAL_API_KEY     = {config['CENTRAL_API_KEY'][:20]}...")
    
    # Demander confirmation
    print("\n")
    confirm = input("Écrire cette configuration dans .env ? (y/n): ").strip().lower()
    
    if confirm == "y":
        write_env_file(config)
        print("\n✓ Configuration terminée !")
        print(f"✓ Prochaine étape : python main.py")
    else:
        print("✗ Configuration annulée")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n✗ Configuration interrompue par l'utilisateur")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Erreur : {e}")
        sys.exit(1)
