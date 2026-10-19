# WIFIZONE — Agent dans un container MikroTik

L'agent du site tourne **dans le routeur lui-même** (container sur clé USB), avec un second
container **Tailscale** pour joindre le PC central où tourne l'orchestrateur n8n.
Plus de PC Ubuntu par site, plus de tunnel SSH à maintenir.

```
        Routeur MikroTik (RouterOS 7 + clé USB ext4)
 ┌────────────────────────────────────────────────────────┐
 │  Hotspot / clients WiFi                                │
 │                                                        │
 │  bridge br-containers 172.31.0.0/24                    │
 │   ├ .1  routeur  ◄── SSH :22 ── agent                  │
 │   ├ .2  wz-tailscale  (proxy SOCKS5 :1055, mode userspace)
 │   └ .3  wz-agent      (API :9001, alertes :9000)       │
 └──────────────────────┬─────────────────────────────────┘
                        │ Internet / Starlink  (WireGuard, chiffré)
                  ┌─────▼──────┐
                  │  Tailnet   │
                  └─────┬──────┘
                        │
              PC central : n8n (:5678)
```

| Sens | Chemin |
|---|---|
| agent → central (métriques, alertes…) | `requests` → proxy SOCKS5 du container Tailscale → tailnet |
| central → agent (`/action`, `/health`…) | n8n → `http://<adresse tailnet du site>:9001` → Tailscale transfère le port 9001 → container agent |
| agent → routeur | SSH vers `172.31.0.1` (identique à avant, sans PC intermédiaire) |

Pourquoi le mode *userspace* de Tailscale : pas de `/dev/net/tun`, pas d'iptables, pas de routage
de sous-réseau à approuver, et indépendant des bugs de version RouterOS. Les sites peuvent tous
utiliser le même sous-réseau `172.31.0.0/24` (il n'est jamais annoncé sur le tailnet).

## 0. Le routeur est-il compatible ?

`/system resource print` → regarder `architecture-name` et `total-memory`.

| Architecture | Supporté ? |
|---|---|
| `arm64`, `x86` | **Oui** (cette image) |
| `arm` (32 bits) | Le container existe, mais **cette image ne se construit pas** (pas de roues `bcrypt`/`cryptography` pour armv7) |
| `mipsbe`, `smips`, `mmips`, `ppc`, `tile` | **Non** — RouterOS n'a pas de containers sur ces architectures |

Il faut aussi : **≥ 512 Mo de RAM** (l'agent ≈ 100 Mo, Tailscale ≈ 50 Mo, plus le hotspot), un port
USB, et une clé/SSD USB **de qualité** (la doc MikroTik recommande ≥ 100 Mo/s). Une clé bon marché
s'use vite (bases SQLite, logs) et ralentit l'extraction des images.

## 1. Préparer le routeur (une seule fois, accès physique requis)

1. RouterOS 7 à jour, puis installer le paquet **`container`** de la même version/architecture
   (téléchargé sur mikrotik.com → *Extra packages*, glissé dans *Files*, puis redémarrage).
2. Activer les containers : `/system device-mode update container=yes`, puis **confirmer
   physiquement** (bouton reset, ou redémarrage à froid sur x86).
3. Formater la clé en **ext4** (Winbox : *System → Disks → Format Drive*). Elle apparaît en `usb1`
   (sinon, changer `disk` dans le script).
4. Vérifier que l'heure du routeur est synchronisée (NTP) et que `/ip dns` est configuré.

## 2. Construire les images (sur un PC avec Docker)

```powershell
# Windows (Docker Desktop)
.\deploy\mikrotik\build.ps1 -Platform linux/arm64
```
```bash
# Linux / macOS
./deploy/mikrotik/build.sh linux/arm64      # ou linux/amd64 pour un CHR
```
Résultat : `deploy/mikrotik/dist/linux-arm64/wz-agent.tar` et `wz-tailscale.tar`.
Ces images ne contiennent **aucun secret** : tout est passé par variables d'environnement.

## 3. Tailscale (console d'administration)

- Créer deux tags (ex. `tag:wz-agent`, `tag:wz-central`) et étiqueter le PC central.
- Générer **une clé d'authentification par site**, associée à `tag:wz-agent` (les machines
  étiquetées n'expirent pas).
- ACL **à ajouter sans retirer les règles existantes** (sinon vous risquez de vous exclure) :
  `tag:wz-central` → `tag:wz-agent:9001` et `tag:wz-agent` → `tag:wz-central:5678`.
  Les sites n'ont aucune raison de se voir entre eux.

## 4. Copier les fichiers sur le routeur

Dans *Files* (Winbox) ou en SFTP :
- `usb1/wifizone/wz-agent.tar`
- `usb1/wifizone/wz-tailscale.tar`
- `wifizone-container.rsc` (à la racine du routeur)

## 5. Configurer et lancer

Éditer la section **PARAMETRES** de `wifizone-container.rsc` (nom du site, IP Tailscale du central,
clé API n8n, clé Tailscale, mot de passe de l'utilisateur agent), puis :

```
/import file-name=wifizone-container.rsc
```
Le script crée le réseau, le pare-feu, l'utilisateur agent, les volumes, les variables et les deux
containers, puis les démarre (l'extraction peut prendre plusieurs minutes). Il peut être relancé
sans danger. N'utilisez pas les caractères `"` `$` `\` `?` dans les secrets.

## 6. Vérifier

```
/container print                  # les deux en "running"
/log print                        # (topic container) démarrage de l'agent et de Tailscale
```
- La machine (`TS_HOSTNAME`) apparaît dans la console Tailscale.
- Depuis le central : `http://<adresse tailnet du site>:9001/health` répond 200.
- Le central reçoit l'enregistrement du site sur `/webhook/register`.

**Adresse du site vue par le central** : par défaut le nom MagicDNS (`wz-site-a`). Si n8n tourne dans
Docker et ne résout pas ce nom, mettre l'IP `100.x` du site :
```
/container envs set [find where list=wz-agent and key=AGENT_TAILSCALE_IP] value=100.x.x.x
/container stop wz-agent
/container start wz-agent
```

## Sécurité

- **Les clients du hotspot ne doivent jamais atteindre les containers** : le proxy SOCKS5 donne accès
  à tout le tailnet. Le script ajoute une règle `forward` qui bloque toute nouvelle connexion vers
  `172.31.0.0/24`. Testez-la : depuis un téléphone connecté au WiFi, `172.31.0.2:1055` ne doit pas répondre.
- Les secrets sont dans `/container envs` : ne partagez jamais un `/export` brut du routeur.
- RouterOS n'offre **aucune garantie d'isolation** pour les containers (cf. doc MikroTik) : n'exécutez
  que vos propres images.
- Si `/ip service ssh` est restreint par adresse, ajoutez `172.31.0.0/24` (le script avertit mais ne
  modifie pas ce réglage).

## Mise à jour d'un site

1. Reconstruire les `.tar`, les recopier sur la clé (même nom).
2. `/container stop wz-agent` puis `/container remove wz-agent`.
3. `/import file-name=wifizone-container.rsc` — les données (`/data`) et l'identité Tailscale
   (`ts-state`) sont conservées sur la clé.

## Ce qui est vérifié, et ce qui ne l'est pas

| | Statut |
|---|---|
| Agent démarre avec **uniquement** des variables d'environnement, avec les dépendances allégées | ✅ testé (Linux, Python 3.13) |
| Données (SQLite, logs rotatifs) écrites dans `DATA_DIR`, rien dans le dossier du code | ✅ testé |
| Trafic vers le central via proxy SOCKS5, réseau local en direct (`NO_PROXY`) | ✅ testé avec un faux proxy |
| Format du forward TCP (`TCP` → `TCPForward`) | ✅ vérifié dans le code source de Tailscale |
| Roues précompilées arm64 / amd64 pour toutes les dépendances | ✅ vérifié |
| Syntaxe des scripts shell, équilibre du script `.rsc` | ✅ vérifié |
| Construction des images Docker | ⚠️ **non exécutée** (pas de Docker dans l'environnement de développement) |
| Exécution du `.rsc` sur un vrai RouterOS | ⚠️ **non testée** — relu contre la doc officielle (syntaxe `list=` / `mountlists=` / `envlist=`) |
| Tailscale réel : proxy SOCKS5 + forward du port 9001 en mode userspace | ⚠️ **non testé** |

Premier déploiement : le faire sur **un seul site**, hors heures de pointe, avant de généraliser.

## Dépannage

| Symptôme | Piste |
|---|---|
| Container bloqué en `extracting` | Clé trop lente ou RAM insuffisante ; attendre, sinon changer de clé |
| L'agent ne se connecte pas au routeur | Règle pare-feu SSH, restriction `/ip service ssh`, mot de passe de `api-agent` |
| Le site n'apparaît pas sur le tailnet | Clé Tailscale invalide/expirée ; `/log print` ; DNS/Internet du routeur |
| Le central reçoit les données mais ne peut pas commander l'agent | Adresse annoncée (nom MagicDNS non résolu → mettre l'IP `100.x`), ACL Tailscale |
| `memory-high non supporté` | Version RouterOS ancienne : sans conséquence, la limite n'est simplement pas appliquée |

## Réglages de sécurité et de rétention (variables d'environnement)

| Variable | Défaut | Effet |
|---|---|---|
| `CONFIRM_DANGER_LEVELS` | `high` | Niveaux `danger` qui exigent `"confirm": true` dans la requête (`high`, `medium,high`, ou `none`) |
| `BACKUP_RETENTION_DAYS` / `BACKUP_MAX_MB` / `BACKUP_KEEP_MIN` | 30 / 200 / 3 | Purge des sauvegardes locales (0 = critère désactivé) |
| `VOUCHER_RETENTION_DAYS` / `VOUCHER_MAX_MB` / `VOUCHER_KEEP_MIN` | 30 / 200 / 0 | Purge des PDF de bons |
| `BACKUP_ROUTER_KEEP_ONLY_LATEST` | `true` | Après un backup téléchargé avec succès, supprime les anciens `.backup` du routeur |

La purge tourne au démarrage, chaque jour, et après chaque backup / export PDF.
