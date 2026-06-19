#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  WIFIZONE Agent — Deploy Script
#  Déploiement headless sur Ubuntu.
#  Usage: sudo ./deploy.sh [options]
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

VERSION="1.0.0"

# ── Couleurs ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'

log_info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ── Valeurs par défaut ────────────────────────────────────────────────────────
INSTALL_DIR="/opt/wifizone-agent"
SERVICE_NAME="wifizone-agent"
SITE_ID=""
SITE_NAME=""
MIKROTIK_HOST=""
MIKROTIK_PASSWORD=""
CENTRAL_HOST=""
API_KEY=""
TAILSCALE_IP=""
DRY_RUN=false
FORCE=false

# ── Aide ──────────────────────────────────────────────────────────────────────
usage() {
    cat <<EOF
WIFIZONE Agent — Deploy Script v${VERSION}

Usage: sudo ./deploy.sh [options]

Options obligatoires :
  --site-id <ID>           Code du site (ex: SITE_B)
  --site-name <NAME>       Nom du site (ex: "WIFIZONE Banikoara")
  --mikrotik-host <IP>     IP du MikroTik local (ex: 192.168.10.1)
  --mikrotik-password <PW> Mot de passe API MikroTik
  --central-host <IP>      IP Tailscale du PC Central (ex: 100.66.77.29)
  --api-key <KEY>          Clé API n8n (32 caractères)

Options optionnelles :
  --install-dir <PATH>     Répertoire d'installation (default: /opt/wifizone-agent)
  --tailscale-ip <IP>      IP Tailscale de cet agent (auto-détectée si omise)
  --dry-run                Simuler sans rien écrire
  --force                  Forcer même si le répertoire existe déjà
  --help                   Afficher cette aide

Exemple :
  sudo ./deploy.sh \\
    --site-id SITE_B \\
    --site-name "WIFIZONE Banikoara" \\
    --mikrotik-host 192.168.10.1 \\
    --mikrotik-password "secret123" \\
    --central-host 100.66.77.29 \\
    --api-key "daabc4e0ba3d529f2f4efbf750073f9f"
EOF
    exit 0
}

# ── Parsing arguments ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --site-id)           SITE_ID="$2"; shift 2 ;;
        --site-name)         SITE_NAME="$2"; shift 2 ;;
        --mikrotik-host)     MIKROTIK_HOST="$2"; shift 2 ;;
        --mikrotik-password) MIKROTIK_PASSWORD="$2"; shift 2 ;;
        --central-host)      CENTRAL_HOST="$2"; shift 2 ;;
        --api-key)           API_KEY="$2"; shift 2 ;;
        --install-dir)       INSTALL_DIR="$2"; shift 2 ;;
        --tailscale-ip)      TAILSCALE_IP="$2"; shift 2 ;;
        --dry-run)           DRY_RUN=true; shift ;;
        --force)             FORCE=true; shift ;;
        --help)              usage ;;
        *) log_error "Argument inconnu : $1"; usage ;;
    esac
done

# ── Validation ────────────────────────────────────────────────────────────────
MISSING=0
for var in SITE_ID SITE_NAME MIKROTIK_HOST MIKROTIK_PASSWORD CENTRAL_HOST API_KEY; do
    if [[ -z "${!var}" ]]; then
        log_error "Option obligatoire manquante : --$(echo "${var,,}" | tr '_' '-')"
        MISSING=1
    fi
done
[[ "$MISSING" -eq 1 ]] && echo && usage

# ── Vérifications préalables ──────────────────────────────────────────────────

# Root check
if [[ "$EUID" -ne 0 ]]; then
    if [[ "$DRY_RUN" == true ]]; then
        log_info "Mode dry-run — pas besoin de root"
        ORIGINAL_USER="${USER:-$(whoami)}"
    else
        log_error "Ce script doit être exécuté avec sudo"
        echo "  Usage: sudo $0 [options]"
        exit 1
    fi
fi

# OS check — Ubuntu only
if [[ ! -f /etc/os-release ]] || ! grep -qi "ubuntu" /etc/os-release 2>/dev/null; then
    log_error "Ce script est conçu pour Ubuntu uniquement"
    echo "  OS détecté : $(grep -oP '(?<=^PRETTY_NAME=").*(?=")' /etc/os-release 2>/dev/null || inconnu)"
    exit 1
fi
OS_VERSION=$(grep -oP '(?<=^VERSION_ID=").*(?=")' /etc/os-release 2>/dev/null || "?")
log_ok "Ubuntu ${OS_VERSION} détecté"

# User original
ORIGINAL_USER="${SUDO_USER:-$(whoami)}"
if [[ "$ORIGINAL_USER" == "root" ]]; then
    log_error "Exécutez avec sudo depuis un utilisateur normal, pas en root direct"
    exit 1
fi
log_ok "Utilisateur : ${ORIGINAL_USER}"

# ── Dry-run mode ──────────────────────────────────────────────────────────────
run() {
    if [[ "$DRY_RUN" == true ]]; then
        echo -e "${YELLOW}[DRY-RUN]${NC} $*"
    else
        "$@"
    fi
}

# ── Résumé ────────────────────────────────────────────────────────────────────
echo
echo -e "${CYAN}══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  WIFIZONE Agent — Déploiement${NC}"
echo -e "${CYAN}══════════════════════════════════════════════════════════════${NC}"
echo "  Site ID         : ${SITE_ID}"
echo "  Site Name       : ${SITE_NAME}"
echo "  MikroTik        : ${MIKROTIK_HOST}"
echo "  Central         : ${CENTRAL_HOST}"
echo "  Install dir     : ${INSTALL_DIR}"
echo "  User            : ${ORIGINAL_USER}"
[[ -n "$TAILSCALE_IP" ]] && echo "  Tailscale IP    : ${TAILSCALE_IP}"
[[ "$DRY_RUN" == true ]] && echo -e "${YELLOW}  Mode            : DRY-RUN (aucune écriture)${NC}"
echo

if [[ "$DRY_RUN" == true ]]; then
    echo -e "${YELLOW}  Mode DRY-RUN : les commandes précédées de [DRY-RUN] seront simulées${NC}"
else
    read -rp "Continuer ? (y/N) " confirm
    [[ "$confirm" != "y" && "$confirm" != "Y" ]] && echo "Annulé." && exit 0
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  1. Prérequis système
# ═══════════════════════════════════════════════════════════════════════════════
echo
log_info "Étape 1/5 : Installation des prérequis système..."

PYTHON_OK=true
command -v python3 &>/dev/null || PYTHON_OK=false
if [[ "$PYTHON_OK" == true ]]; then
    PY_VER=$(python3 --version 2>&1 | grep -oP '\d+\.\d+')
    MAJOR="${PY_VER%.*}"; MINOR="${PY_VER#*.}"
    if [[ "$MAJOR" -lt 3 || ( "$MAJOR" -eq 3 && "$MINOR" -lt 9 ) ]]; then
        log_error "Python 3.9+ requis (version détectée : ${PY_VER})"
        log_info "Pour installer Python 3.11 : sudo apt install python3.11 python3.11-venv"
        exit 1
    fi
    log_ok "Python ${PY_VER} détecté"
fi

if [[ "$DRY_RUN" != true ]]; then
    apt-get update -qq || log_warn "apt-get update a échoué (peut-être déjà à jour)"
    apt-get install -y -qq python3 python3-venv python3-pip openssh-client curl
    log_ok "Prérequis installés"
else
    run apt-get update -qq
    run apt-get install -y -qq python3 python3-venv python3-pip openssh-client curl
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  2. Installation des fichiers
# ═══════════════════════════════════════════════════════════════════════════════
echo
log_info "Étape 2/5 : Installation dans ${INSTALL_DIR}..."

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ -d "$INSTALL_DIR" && "$FORCE" != true ]]; then
    log_error "Le répertoire ${INSTALL_DIR} existe déjà."
    echo "  Utilisez --force pour écraser, ou choisissez un autre --install-dir"
    exit 1
fi

run mkdir -p "$INSTALL_DIR"

# Copier en excluant venv/, .db, caches, logs
run rsync -a --exclude='venv/' --exclude='*.db' --exclude='*.db-shm' --exclude='*.db-wal' \
    --exclude='__pycache__' --exclude='.pytest_cache' --exclude='logs/' \
    --exclude='backups/' --exclude='vouchers/' \
    "$SCRIPT_DIR/" "$INSTALL_DIR/" 2>/dev/null || (
    # Fallback si rsync n'est pas installé : copie fichier par fichier
    for item in core workers scripts config *.py *.txt Makefile deploy.sh wifizone-agent.service; do
        [[ -e "$SCRIPT_DIR/$item" ]] && run cp -r "$SCRIPT_DIR/$item" "$INSTALL_DIR/"
    done
)

log_ok "Fichiers copiés dans ${INSTALL_DIR}"

# ═══════════════════════════════════════════════════════════════════════════════
#  3. Environnement Python
# ═══════════════════════════════════════════════════════════════════════════════
echo
log_info "Étape 3/5 : Création de l'environnement Python..."

run python3 -m venv "$INSTALL_DIR/venv"
run chown -R "${ORIGINAL_USER}:${ORIGINAL_USER}" "$INSTALL_DIR/venv"
run "$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
run "$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
log_ok "Environnement Python créé et dépendances installées"

# ═══════════════════════════════════════════════════════════════════════════════
#  4. Configuration .env
# ═══════════════════════════════════════════════════════════════════════════════
echo
log_info "Étape 4/5 : Écriture du fichier .env..."

# Partir du template .env.site_a, créer .env
ENV_FILE="$INSTALL_DIR/.env"

# En dry-run, créer un fichier temporaire pour valider la syntaxe des sed
_create_env() {
    if [[ -f "$INSTALL_DIR/.env.site_a" ]]; then
        cp "$INSTALL_DIR/.env.site_a" "$1"
    else
        cat > "$1" <<-ENVEOF
# WIFIZONE Agent — Généré par deploy.sh v${VERSION}
SITE_ID=dummy
SITE_NAME=dummy
MIKROTIK_HOST=dummy
MIKROTIK_PASSWORD=dummy
CENTRAL_HOST=dummy
CENTRAL_API_KEY=dummy
AGENT_TAILSCALE_IP=
MIKROTIK_PORT=8728
MIKROTIK_SSH_PORT=22
MIKROTIK_USER=api-agent
MIKROTIK_ROS_VERSION=7
CENTRAL_PORT=5678
ALERT_PORT=9000
COMMAND_PORT=9001
ENVEOF
    fi
}

if [[ "$DRY_RUN" == true ]]; then
    # Créer un .env temporaire pour que les sed qui suivent ne cassent pas
    TMP_ENV=$(mktemp)
    _create_env "$TMP_ENV"
    ENV_FILE="$TMP_ENV"
    log_info "Fichier .env sera créé avec les valeurs du site ${SITE_ID}"
    # Afficher les valeurs principales
    echo "    SITE_ID          = ${SITE_ID}"
    echo "    SITE_NAME        = ${SITE_NAME}"
    echo "    MIKROTIK_HOST    = ${MIKROTIK_HOST}"
    echo "    CENTRAL_HOST     = ${CENTRAL_HOST}"
    [[ -n "$TAILSCALE_IP" ]] && echo "    AGENT_TAILSCALE_IP= ${TAILSCALE_IP}"
else
    _create_env "$ENV_FILE"
fi

# Surcharger les valeurs avec sed (idempotent)
run sed -i "s/^SITE_ID=.*/SITE_ID=${SITE_ID}/" "$ENV_FILE"
run sed -i "s/^SITE_NAME=.*/SITE_NAME=${SITE_NAME}/" "$ENV_FILE"
run sed -i "s/^MIKROTIK_HOST=.*/MIKROTIK_HOST=${MIKROTIK_HOST}/" "$ENV_FILE"
run sed -i "s/^MIKROTIK_PASSWORD=.*/MIKROTIK_PASSWORD=${MIKROTIK_PASSWORD}/" "$ENV_FILE"
run sed -i "s/^CENTRAL_HOST=.*/CENTRAL_HOST=${CENTRAL_HOST}/" "$ENV_FILE"
run sed -i "s/^CENTRAL_API_KEY=.*/CENTRAL_API_KEY=${API_KEY}/" "$ENV_FILE"

# Tailscale IP optionnelle
if [[ -n "$TAILSCALE_IP" ]]; then
    if grep -q "^AGENT_TAILSCALE_IP=" "$ENV_FILE" 2>/dev/null; then
        run sed -i "s/^AGENT_TAILSCALE_IP=.*/AGENT_TAILSCALE_IP=${TAILSCALE_IP}/" "$ENV_FILE"
    else
        run echo "AGENT_TAILSCALE_IP=${TAILSCALE_IP}" >> "$ENV_FILE"
    fi
fi

if [[ "$DRY_RUN" == true ]]; then
    rm -f "$ENV_FILE"
else
    run chown "${ORIGINAL_USER}:${ORIGINAL_USER}" "$ENV_FILE"
fi

log_ok ".env configuré avec les paramètres du site ${SITE_ID}"

# ═══════════════════════════════════════════════════════════════════════════════
#  5. Service systemd
# ═══════════════════════════════════════════════════════════════════════════════
echo
log_info "Étape 5/5 : Installation du service systemd..."

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ -f "$INSTALL_DIR/wifizone-agent.service" ]]; then
    # Adapter le service : remplacer user + path
    run sed -e "s|User=ubuntu|User=${ORIGINAL_USER}|g" \
            -e "s|/opt/wifizone-agent|${INSTALL_DIR}|g" \
            "$INSTALL_DIR/wifizone-agent.service" > "/tmp/${SERVICE_NAME}.service"
    run cp "/tmp/${SERVICE_NAME}.service" "$SERVICE_FILE"
    run rm "/tmp/${SERVICE_NAME}.service"
else
    # Créer un service minimal
    run tee "$SERVICE_FILE" > /dev/null <<-SRVEOF
[Unit]
Description=WIFIZONE Site Agent — ${SITE_ID}
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
Type=simple
User=${ORIGINAL_USER}
WorkingDirectory=${INSTALL_DIR}
Environment=ENV_PATH=${INSTALL_DIR}/.env
Environment=LOG_LEVEL=INFO
ExecStart=${INSTALL_DIR}/venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SRVEOF
fi

run chmod 644 "$SERVICE_FILE"
run systemctl daemon-reload
run systemctl enable "${SERVICE_NAME}"
log_ok "Service systemd installé et activé"

# ── Permissions ───────────────────────────────────────────────────────────────
run chown -R "${ORIGINAL_USER}:${ORIGINAL_USER}" "$INSTALL_DIR"
# S'assurer que deploy.sh reste exécutable
run chmod +x "$INSTALL_DIR/deploy.sh"

# ═══════════════════════════════════════════════════════════════════════════════
#  Finalisation
# ═══════════════════════════════════════════════════════════════════════════════
if [[ "$DRY_RUN" == false ]]; then
    echo
    echo -e "${GREEN}══════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  ✅ WIFIZONE Agent installé avec succès !${NC}"
    echo -e "${GREEN}══════════════════════════════════════════════════════════════${NC}"
    echo
    echo "  Site    : ${SITE_ID} — ${SITE_NAME}"
    echo "  Path    : ${INSTALL_DIR}"
    echo "  User    : ${ORIGINAL_USER}"
    echo
    echo -e "  Démarrer le service : ${CYAN}sudo systemctl start ${SERVICE_NAME}${NC}"
    echo -e "  Voir les logs        : ${CYAN}sudo journalctl -u ${SERVICE_NAME} -f${NC}"
    echo -e "  Statut               : ${CYAN}sudo systemctl status ${SERVICE_NAME}${NC}"
    echo
    echo -e "  ${YELLOW}Vérifiez que Tailscale est actif avant de démarrer.${NC}"
    echo

    # Tentative de démarrage
    log_info "Démarrage du service..."
    systemctl start "${SERVICE_NAME}" || log_warn "Le démarrage a échoué — vérifiez les logs"

    # Vérification
    sleep 2
    if systemctl is-active --quiet "${SERVICE_NAME}"; then
        log_ok "Service actif !"
    else
        log_warn "Le service n'est pas actif — lancez : sudo journalctl -u ${SERVICE_NAME} -n 30"
    fi

    # Test health endpoint
    echo
    log_info "Vérification de l'endpoint /health..."
    if command -v curl &>/dev/null; then
        HEALTH_STATUS=$(curl -sf http://127.0.0.1:9000/health 2>/dev/null || echo "")
        if [[ -n "$HEALTH_STATUS" ]]; then
            log_ok "Agent opérationnel — réponse /health : ${HEALTH_STATUS}"
        else
            log_warn "Impossible de joindre /health (peut-être encore en démarrage)"
        fi
    fi
else
    echo
    echo -e "${YELLOW}══════════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}  🏁 DRY-RUN terminé — aucune modification${NC}"
    echo -e "${YELLOW}══════════════════════════════════════════════════════════════${NC}"
    echo
    echo "  Pour déployer pour de vrai :"
    echo "    sudo ./deploy.sh [options]"
    echo
fi
