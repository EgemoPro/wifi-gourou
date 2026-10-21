# wifi-gourou — Agent WIFIZONE

Agent de gestion centralisée de sites MikroTik via SSH. Il exécute des actions RouterOS (hotspot, vouchers, profils, réseau, système, diagnostic), collecte des métriques, détecte les anomalies et envoie le tout à l'orchestrateur n8n du central. Un agent par site ; le central pilote chaque agent par HTTP.

Fonctionne sous **Linux et Windows** (`python main.py`), en service systemd, ou **dans un container sur le routeur MikroTik** lui-même (voir [deploy/mikrotik](deploy/mikrotik/README.md)).

## Architecture

```
wifi-gourou/
├── core/                  # Moteur de l'agent
│   ├── ssh.py             # Connexion SSH vers MikroTik (pool, reconnexion, rendu des scripts .rsc)
│   ├── executor.py        # Pipeline d'exécution : validation → confirmation → script/handler → réponse
│   ├── registry.py        # Registre des actions (commands.json) et résolution des alias
│   ├── validator.py       # Validation des paramètres + confirmation des actions dangereuses
│   ├── retention.py       # Purge automatique des backups et PDF
│   ├── paths.py           # Dossier de données (DATA_DIR)
│   ├── storage.py         # Persistance SQLite (commandes, métriques, événements)
│   ├── queue.py           # File durable SQLite (messages à renvoyer au central)
│   ├── forwarding.py      # Envoi vers n8n avec reprises, enregistrement du site
│   └── utils.py           # Utilitaires et format de réponse standard
├── workers/
│   ├── metrics.py         # Collecte et contrôles (CPU, clients, bande passante, hors-ligne, comptes, schedulers)
│   └── heartbeat.py       # Raccourci de compatibilité (le signal de vie est géré par main.py)
├── scripts/routeros/      # Scripts .rsc par catégorie
│   ├── hotspot/           # Utilisateurs, sessions, profils, vouchers
│   ├── network/           # MAC bloquées, WAN, DHCP, WiFi, voisins, consommateurs
│   ├── system/            # Uptime, logs, certificats, firmware, redémarrage
│   └── diagnostics/       # Santé, informations, interfaces, schedulers
├── config/
│   └── commands.json      # Définition des 35 actions (paramètres, danger, alias, timeout)
├── deploy/mikrotik/       # Déploiement en container sur le routeur (agent + Tailscale)
├── main.py                # API FastAPI (ports 9000 alertes / 9001 commandes) et tâches de fond
├── config.py              # Configuration par variables d'environnement / .env
├── models.py              # Modèles de données (Pydantic)
├── voucher_pdf.py         # Génération de tickets PDF (QR codes)
├── collector.py           # Raccourci de compatibilité vers workers/metrics.py
├── deploy.sh              # Déploiement headless (systemd)
├── wifizone-agent.service # Unité systemd
├── mikrotik-agent-setup.rsc  # Script à exécuter sur le routeur pour créer l'utilisateur SSH
├── setup.py / test.py     # Configuration interactive et test de connectivité
├── diagnostic.py          # Diagnostic de l'agent
├── requirements.txt       # Dépendances Python
└── tests/                 # 282 tests
```

## Quick Start

```bash
# 1. Copier et paramétrer la configuration
cp .env.site_a .env
# Éditer SITE_ID, SITE_NAME, MIKROTIK_HOST, MIKROTIK_PASSWORD, CENTRAL_HOST, CENTRAL_API_KEY

# 2. Lancer l'agent (mode développement)
python main.py

# 3. Tester une action
curl -X POST http://localhost:9001/action \
  -H "Content-Type: application/json" \
  -H "X-API-Key: votre_cle_api" \
  -d '{"action": "hotspot.list_active"}'
```

Au démarrage, si le routeur est injoignable, l'agent démarre quand même, sert l'API et réessaie en arrière-plan.

## Actions disponibles (35)

Chaque action a un niveau de **danger** (`low`, `medium`, `high`) et des **alias** (anciens noms, par ex. `get_active_users` → `hotspot.list_active`). `GET /actions` et `GET /capabilities` listent les actions de l'agent.

### Hotspot — utilisateurs et sessions (9)
| Action | Danger | Description |
|---|---|---|
| `hotspot.create_user` | low | Créer un utilisateur (profil, commentaire, quota de données, durée) |
| `hotspot.delete_user` | medium | Supprimer un utilisateur |
| `hotspot.enable_user` | low | Réactiver un utilisateur |
| `hotspot.disable_user` | low | Désactiver un utilisateur |
| `hotspot.kick_user` | low | Déconnecter un utilisateur actif |
| `hotspot.list_active` | low | Lister les utilisateurs actifs |
| `hotspot.active_sessions` | low | Sessions actives détaillées avec consommation |
| `hotspot.list_users` | low | Lister tous les comptes |
| `hotspot.list_vouchers` | low | Lister les vouchers générés |

### Hotspot — vouchers (2)
| Action | Danger | Description |
|---|---|---|
| `hotspot.vouchers` | low | Générer des codes (quantité, profil, mode voucher ou utilisateur/mot de passe, longueur, jeu de caractères, prix, URL de connexion) |
| `export_pdf` | low | Exporter une liste de vouchers en PDF imprimable (32 tickets par page, QR code) |

### Hotspot — profils (5)
| Action | Danger | Description |
|---|---|---|
| `profile.create` | medium | Créer un profil avec limitation de débit, utilisateurs partagés, timeouts, quota |
| `profile.update` | medium | Mettre à jour un profil existant |
| `profile.list` | low | Lister les profils |
| `profile.delete` | **high** | Supprimer un profil (comptes et scheduler de nettoyage associés) |
| `hotspot.setup_profile` | medium | Configurer l'expiration absolue (script on-login + scheduler de nettoyage), verrouillage MAC |

### Contrôle des adresses MAC (2)
| Action | Danger | Description |
|---|---|---|
| `hotspot.block_mac` | medium | Bloquer une adresse MAC (address-list) |
| `hotspot.unblock_mac` | medium | Débloquer une adresse MAC |

### Réseau (7)
| Action | Danger | Description |
|---|---|---|
| `network.list_blocklist` | low | Address-lists du pare-feu |
| `network.list_wireless` | low | Clients WiFi connectés (Wave2 et Legacy) |
| `network.wan_info` | low | IP, passerelle, DNS du WAN |
| `network.dhcp_leases` | low | Baux DHCP |
| `network.top_users` | low | Plus gros consommateurs (files d'attente + sessions) |
| `network.neighbors` | low | Équipements voisins (LLDP/CDP/MNDP) |
| `network.interfaces` | low | Interfaces réseau et leur statut |

### Système (5)
| Action | Danger | Description |
|---|---|---|
| `system.uptime` | low | Ressources, uptime et historique |
| `system.logs` | low | Logs critiques, erreurs et récents |
| `system.certificates` | low | État des certificats SSL |
| `system.firmware` | low | Firmware RouterBOARD |
| `system.scheduler_list` | low | Scripts planifiés |

### Routeur (5)
| Action | Danger | Description |
|---|---|---|
| `router.health` | low | Santé du routeur (CPU, mémoire, température) |
| `router.info` | low | Informations système détaillées |
| `router.check_update` | low | Mises à jour RouterOS disponibles (lecture seule) |
| `router.backup` | low | Sauvegarde de la configuration, téléchargée en SFTP |
| `router.reboot` | **high** | Redémarrer le routeur |

### Sécurité des actions

- **Confirmation obligatoire** : une action `high` (`profile.delete`, `router.reboot`) est refusée avec l'erreur `CONFIRMATION_REQUIRED` tant que la requête ne contient pas `"confirm": true`. Le refus n'est pas mémorisé : renvoyer la même requête avec `confirm` fonctionne. Le niveau se règle avec `CONFIRM_DANGER_LEVELS` (`high` par défaut, `medium,high`, ou `none`).
- **Prévisualisation** : `"mode": "preview"` montre ce qui serait exécuté sans rien envoyer au routeur, et indique `requires_confirmation`.
- **Idempotence** : un `command_id` identique renvoie le résultat déjà enregistré au lieu de ré-exécuter l'action.
- **Validation** : types, bornes et motifs des paramètres déclarés dans `commands.json` ; les paramètres non déclarés sont écartés. Les scripts RouterOS sont déterministes (fichiers `.rsc` + paramètres injectés), jamais composés à partir de texte libre.

## Installation

### Prérequis
- Python 3.9+ (testé en 3.13), Linux ou Windows
- MikroTik RouterOS 7 avec accès SSH (port 22)
- n8n (central) joignable depuis l'agent, directement ou par Tailscale

### Déploiement headless

```bash
# Test en dry-run
sudo ./deploy.sh --dry-run

# Installation réelle
sudo ./deploy.sh --site-id SITE_A --site-name "Site A" \
  --mikrotik-host 192.168.88.1 --mikrotik-password '...' \
  --central-host 100.64.0.10 --api-key '...' \
  --install-dir /opt/wifizone-agent
```

Options : `--site-id`, `--site-name`, `--mikrotik-host`, `--mikrotik-password`, `--central-host`, `--api-key`, `--install-dir`, `--tailscale-ip`, `--dry-run`, `--force`, `--help`.

Le script `deploy.sh` gère automatiquement :
- Installation des dépendances Python
- Création du service systemd
- Configuration du fichier `.env`
- Démarrage de l'agent

### Déploiement en container sur le routeur MikroTik

L'agent peut tourner sur le routeur lui-même (clé USB ext4, RouterOS 7, arm64 ou x86, 512 Mo de RAM minimum), avec un second container **Tailscale** qui relie le site au PC central. Un script RouterOS idempotent crée le réseau, le pare-feu, l'utilisateur SSH de l'agent, les volumes et les deux containers. Les données (bases SQLite, logs, backups, PDF) vivent dans `DATA_DIR`, sur la clé. Guide complet, limites et statut de vérification : [deploy/mikrotik/README.md](deploy/mikrotik/README.md).

### Configuration

```bash
# Copier et éditer le template
cp .env.site_a .env
```

En container, tout se passe par variables d'environnement (aucun fichier `.env` nécessaire).

Variables essentielles :

| Variable | Défaut | Description |
|---|---|---|
| `SITE_ID` | obligatoire | Identifiant du site (SITE_A, SITE_B...) |
| `SITE_NAME` | obligatoire | Nom lisible du site |
| `MIKROTIK_HOST` | obligatoire | IP du routeur MikroTik |
| `MIKROTIK_PASSWORD` | obligatoire | Mot de passe de l'utilisateur SSH |
| `MIKROTIK_USER` | `admin` | Utilisateur SSH |
| `MIKROTIK_SSH_PORT` | `22` | Port SSH |
| `CENTRAL_HOST` | obligatoire | Adresse du central (n8n) |
| `CENTRAL_PORT` | `5678` | Port du central |
| `CENTRAL_API_KEY` | vide | Clé API échangée avec le central (en-tête `X-API-Key`) |
| `AGENT_TAILSCALE_IP` | vide | Adresse du site annoncée au central |
| `COMMAND_PORT` / `ALERT_PORT` | `9001` / `9000` | Ports de l'API de commandes et de réception d'alertes |
| `SSH_TIMEOUT` | `15` | Délai SSH en secondes |
| `DATA_DIR` | dossier du code | Dossier des données persistantes (bases, logs, backups, PDF) |
| `ENV_PATH` | `.env` du code | Chemin d'un fichier `.env` alternatif |

Autres variables : `MIKROTIK_PORT` (ancien port API, 8728), `MIKROTIK_REST_PORT`, `MIKROTIK_ROS_VERSION`.

Sécurité et rétention :

| Variable | Défaut | Effet |
|---|---|---|
| `CONFIRM_DANGER_LEVELS` | `high` | Niveaux de danger qui exigent `"confirm": true` |
| `BACKUP_RETENTION_DAYS` / `BACKUP_MAX_MB` / `BACKUP_KEEP_MIN` | 30 / 200 / 3 | Purge des sauvegardes locales (0 = critère désactivé) |
| `VOUCHER_RETENTION_DAYS` / `VOUCHER_MAX_MB` / `VOUCHER_KEEP_MIN` | 30 / 200 / 0 | Purge des PDF de bons |
| `BACKUP_ROUTER_KEEP_ONLY_LATEST` | `true` | Après un backup téléchargé avec succès, supprime les anciens `.backup` du routeur |

### Tâches automatiques

| Tâche | Fréquence (variable) | Rôle |
|---|---|---|
| Métriques | 300 s (`INTERVAL_METRICS`) | CPU, mémoire, utilisateurs ; alerte CPU au-delà de `THRESHOLD_CPU` (80 %) sur `THRESHOLD_CPU_CYCLES` cycles |
| Clients | 60 s (`INTERVAL_CLIENTS`) | Clients connectés |
| Bande passante | 120 s (`INTERVAL_BANDWIDTH`) | Alerte sur consommation suspecte (`THRESHOLD_BANDWIDTH_MB`, 500 Mo) |
| Routeur hors ligne | 120 s (`INTERVAL_OFFLINE`) | Alerte après `THRESHOLD_OFFLINE_RETRIES` échecs (3) |
| Diagnostics | 3600 s (`INTERVAL_USER_BLOAT`) | Trop de comptes (`THRESHOLD_MAX_USERS`, 200) ou de schedulers (`THRESHOLD_MAX_SCHEDULERS`, 20) |
| Backup quotidien | à `BACKUP_HOUR` (2 h) | Sauvegarde du routeur, résultat envoyé au central |
| Vidage de la file | 60 s (`INTERVAL_QUEUE_FLUSH`) | Renvoie au central les messages en attente |
| Maintenance | 24 h ± 1 h | Nettoyage des files, de la base SQLite et des fichiers (rétention) |
| Enregistrement | `REGISTER_RETRY` (60 s) | Annonce du site au central, avec reprises |

La purge des fichiers tourne aussi au démarrage, après chaque backup et après chaque export PDF. Les messages que le central ne peut pas recevoir sont conservés dans la file durable puis renvoyés avec temporisation croissante.

Remarque : `INTERVAL_SCHEDULERS` est lu mais n'a pas d'effet, la vérification des schedulers suit `INTERVAL_USER_BLOAT`.

## API

Deux serveurs : **9001** (commandes, consultation) et **9000** (réception des alertes du routeur). Toutes les routes protégées attendent l'en-tête `X-API-Key`.

### Endpoints (port 9001)

| Méthode | Route | Auth | Description |
|---|---|---|---|
| `POST` | `/action` | oui | Exécuter une action `{action, payload, mode, command_id}` |
| `POST` | `/command` | oui | Ancien format `{command, params}`, redirigé vers `/action` |
| `GET` | `/health` | non | Santé de l'agent, files, stockage, dernières métriques |
| `GET` | `/actions` | oui | Actions disponibles |
| `GET` | `/capabilities` | oui | Capacités de l'agent |
| `GET` | `/commands` | oui | Historique des commandes exécutées |
| `GET` | `/events` | oui | Journal des événements |
| `GET` | `/metrics` | oui | Dernières métriques collectées |
| `GET` | `/queue` | oui | État de la file d'envoi |
| `GET` | `/queue/durable` | oui | Messages de la file durable (en attente, en reprise, abandonnés) |
| `GET` | `/storage` | oui | Statistiques du stockage SQLite |
| `GET` | `/download/{fichier}` | oui | Télécharger un PDF de bons ou un backup généré |
| `GET` | `/debug/stacks` | non | Piles des threads Python, pour diagnostic : ne pas exposer en dehors du VPN |

### Endpoint (port 9000)

| Méthode | Route | Auth | Description |
|---|---|---|---|
| `POST` | `/alert` | oui | Réception des alertes brutes envoyées par le routeur |

Limites de débit : 100 requêtes par minute par route, 10 par seconde pour `/action`.

### Exécuter une action

```bash
curl -X POST http://localhost:9001/action \
  -H "Content-Type: application/json" \
  -H "X-API-Key: votre_cle_api" \
  -d '{"action": "hotspot.create_user", "payload": {"username": "client001", "password": "1234", "profile": "2h"}, "command_id": "n8n-0001"}'
```

Exemple de réponse :

```json
{
  "command_id": "n8n-0001",
  "action": "hotspot.create_user",
  "site_id": "SITE_A",
  "status": "success",
  "output": { "...": "résultat de l'action" },
  "execution_time_ms": 134,
  "timestamp": "2026-06-21T08:30:00Z"
}
```

### Cas d'erreur

```json
{
  "command_id": "n8n-0002",
  "action": "profile.delete",
  "site_id": "SITE_A",
  "status": "failed",
  "error": {
    "type": "CONFIRMATION_REQUIRED",
    "message": "…",
    "danger": "high",
    "hint": "Renvoyer la même requête avec \"confirm\": true"
  },
  "timestamp": "2026-06-21T08:31:00Z"
}
```

Autres types d'erreur : paramètre invalide, action inconnue, erreur SSH, erreur d'exécution.

## Tests

```bash
# Lancement des tests
python -m pytest tests/ -v

# Avec couverture
python -m pytest tests/ --cov=. --cov-report=term
```

282 tests. `tests/test_executor.py`, `tests/test_metrics.py` et `tests/test_ssh.py` utilisent d'anciens mocks SSH et se bloquent actuellement : à mettre à jour. Les autres fichiers passent, dont `tests/test_risk_and_retention.py` (confirmation des actions dangereuses et rétention des fichiers).

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
