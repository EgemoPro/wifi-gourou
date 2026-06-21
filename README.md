# wifi-gourou — Agent WIFIZONE

Agent de gestion centralisée de sites MikroTik via SSH. Exécute des actions RouterOS (hotspot, réseau, système, diagnostic) et synchronise les résultats vers n8n.

## Architecture

```
wifizone-agent/
├── core/               # Moteur de l'agent
│   ├── ssh.py          # Connexion SSH vers MikroTik
│   ├── executor.py     # Exécution des scripts .rsc
│   ├── registry.py     # Auto-enregistrement de l'agent
│   ├── validator.py    # Validation des paramètres d'actions
│   ├── storage.py      # Persistance SQLite (logs, cache)
│   ├── queue.py        # File offline pour actions différées
│   ├── forwarding.py   # Forwarding des résultats vers n8n
│   └── utils.py        # Utilitaires
├── workers/
│   ├── metrics.py      # Collecte périodique de métriques
│   └── heartbeat.py    # Signal de vie vers le central
├── scripts/routeros/   # Scripts .rsc par catégorie
│   ├── hotspot/        # Gestion des utilisateurs hotspot
│   ├── network/        # Configuration réseau
│   ├── system/         # Administration système
│   └── diagnostics/    # Diagnostics et monitoring
├── config/
│   └── commands.json   # Définition des 27 actions
├── main.py             # API FastAPI (ports 9000/9001)
├── config.py           # Configuration et validation .env
├── deploy.sh           # Script de déploiement headless
├── mikrotik-agent-setup.rsc  # Script à exécuter sur le routeur pour créer l'utilisateur SSH
├── collector.py        # Collecteur de logs complémentaire
├── models.py           # Modèles de données SQLAlchemy
├── voucher_pdf.py      # Génération de tickets PDF
├── requirements.txt    # Dépendances Python
└── tests/              # 224 tests unitaires
```

## Quick Start

```bash
# 1. Copier et paramétrer la configuration
cp .env.site_a .env
# Éditer SITE_ID, MIKROTIK_HOST, MIKROTIK_USER, CENTRAL_API_KEY

# 2. Lancer l'agent (mode développement)
python main.py

# 3. Tester une commande
curl -X POST http://localhost:9001/command \
  -H "Content-Type: application/json" \
  -H "X-API-Key: votre_cle_api" \
  -d '{"action": "hotspot.list_active"}'
```

## Actions disponibles (27)

### Hotspot (8)
| Action | Description |
|---|---|
| `hotspot.create_user` | Créer un utilisateur hotspot |
| `hotspot.delete_user` | Supprimer un utilisateur |
| `hotspot.enable_user` | Activer un utilisateur |
| `hotspot.disable_user` | Désactiver un utilisateur |
| `hotspot.kick_user` | Déconnecter un utilisateur |
| `hotspot.list_active` | Lister les sessions actives |
| `hotspot.list_profiles` | Lister les profils |
| `hotspot.create_profile` | Créer un profil |

### Réseau (8)
| Action | Description |
|---|---|
| `network.block_mac` | Bloquer une adresse MAC |
| `network.unblock_mac` | Débloquer une adresse MAC |
| `network.list_blocklist` | Liste des MAC bloquées |
| `network.list_wireless` | Liste des interfaces sans-fil |
| `network.wan_info` | Informations WAN |
| `network.dhcp_leases` | Baux DHCP actifs |
| `network.top_users` | Top consommateurs |
| `network.neighbors` | Voisins réseau |

### Système (4)
| Action | Description |
|---|---|
| `system.uptime` | Uptime et ressources |
| `system.logs` | Logs système |
| `system.certificates` | Certificats SSL |
| `system.firmware` | Version firmware |

### Diagnostics (4)
| Action | Description |
|---|---|
| `diagnostics.health` | Santé générale du site |
| `diagnostics.info` | Informations détaillées |
| `diagnostics.interfaces` | État des interfaces |
| `diagnostics.schedulers` | Schedulers actifs |

### Actions à risque (3)
| Action | Risque |
|---|---|
| `system.reboot` | Redémarre le routeur |
| `network.check_update` | Vérifie les mises à jour |
| `hotspot.kick_user` | Déconnecte un client |

## Installation

### Prérequis
- Python 3.9+
- MikroTik avec accès SSH (port 22)
- n8n (central)

### Déploiement headless

```bash
# Test en dry-run
sudo ./deploy.sh --dry-run

# Installation réelle
sudo ./deploy.sh --install-dir /opt/wifizone-agent --user venom

# Avec clé SSH personnalisée
sudo ./deploy.sh --ssh-key ~/.ssh/mikrotik_key --user venom
```

Le script `deploy.sh` gère automatiquement :
- Installation des dépendances Python
- Création du service systemd
- Configuration du fichier `.env`
- Démarrage de l'agent

### Configuration

```bash
# Copier et éditer le template
cp .env.site_a .env
# Éditer les paramètres : SITE_ID, API_KEY, MIKROTIK_*, N8N_*
```

Variables essentielles :

| Variable | Description |
|---|---|
| `SITE_ID` | Identifiant du site (SITE_A, SITE_B...) |
| `MIKROTIK_HOST` | IP du routeur MikroTik |
| `MIKROTIK_PORT` | Port SSH (défaut : 22) |
| `MIKROTIK_USER` | Utilisateur SSH |
| `CENTRAL_API_KEY` | Clé API pour le central n8n |
| `N8N_WEBHOOK_URL` | URL du webhook n8n |

## API

### Endpoints

| Méthode | Route | Description |
|---|---|---|
| `POST` | `/command` | Exécuter une action |
| `GET` | `/health` | Santé de l'agent |
| `GET` | `/info` | Informations site |
| `GET` | `/metrics` | Métriques collectées |
| `POST` | `/voucher/generate` | Générer des tickets PDF |

### Exécuter une commande

```bash
curl -X POST http://localhost:9001/command \
  -H "Content-Type: application/json" \
  -H "X-API-Key: votre_cle_api" \
  -d '{"action": "hotspot.list_active"}'
```

Exemple de réponse :

```json
{
  "status": "success",
  "action": "hotspot.list_active",
  "site_id": "SITE_A",
  "data": [
    {
      "user": "client001",
      "address": "192.168.1.42",
      "uptime": "2h15m",
      "bytes_in": 52428800,
      "bytes_out": 10485760
    }
  ],
  "execution_time_ms": 134,
  "timestamp": "2026-06-21T08:30:00Z"
}
```

### Cas d'erreur

```json
{
  "status": "error",
  "action": "hotspot.delete_user",
  "site_id": "SITE_A",
  "error": "User not found",
  "execution_time_ms": 45,
  "timestamp": "2026-06-21T08:31:00Z"
}
```

## Tests

```bash
# Lancement des tests
python -m pytest tests/ -v

# Avec couverture
python -m pytest tests/ --cov=. --cov-report=term

# 224 tests — aucun échec attendu
```

## Makefile

```bash
make help         # Affiche toutes les commandes disponibles
```

### Configuration
| Commande | Description |
|---|---|
| `make setup` | Configuration interactive (.env) |
| `make test` | Tests de connectivité |

### Développement
| Commande | Description |
|---|---|
| `make install-deps` | Installer les dépendances Python |
| `make run` | Démarrer l'agent en mode développement |
| `make debug` | Démarrer en mode DEBUG (logs verbeux) |

### Production (systemd)
| Commande | Description |
|---|---|
| `make install-service` | Installer le service systemd |
| `make start-service` | Démarrer le service |
| `make stop-service` | Arrêter le service |
| `make status` | État du service |
| `make logs` | Logs en temps réel |

### Maintenance
| Commande | Description |
|---|---|
| `make clean` | Nettoyer caches et logs |
| `make uninstall` | Désinstaller complètement (service + fichiers + base) |

## Licence

Propriétaire — WIFIZONE © 2026
