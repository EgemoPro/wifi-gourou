#!/usr/bin/env bash
# Construit les 2 images (agent + tailscale) au format tar importable par RouterOS.
#
# Usage :  ./deploy/mikrotik/build.sh [linux/arm64|linux/amd64]
#   - linux/arm64 : hAP ax2/ax3, RB5009, L009...   (défaut)
#   - linux/amd64 : CHR / x86
# Variables : TS_VERSION (défaut v1.104.1)
#
# Résultat : deploy/mikrotik/dist/<plateforme>/wz-agent.tar et wz-tailscale.tar
# -> à copier dans <clé USB>/wifizone/ sur le routeur.
set -euo pipefail

PLATFORM="${1:-linux/arm64}"
TS_VERSION="${TS_VERSION:-v1.104.1}"

cd "$(dirname "$0")/../.."
OUT="deploy/mikrotik/dist/${PLATFORM//\//-}"
mkdir -p "$OUT"

echo "==> Agent ($PLATFORM)"
docker buildx build \
    --platform "$PLATFORM" \
    -f deploy/mikrotik/Dockerfile \
    -t wifizone/agent:local \
    --output "type=docker,dest=$OUT/wz-agent.tar" \
    .

echo "==> Tailscale $TS_VERSION ($PLATFORM)"
docker buildx build \
    --platform "$PLATFORM" \
    -f deploy/mikrotik/tailscale/Dockerfile \
    --build-arg "TS_VERSION=$TS_VERSION" \
    -t wifizone/tailscale:local \
    --output "type=docker,dest=$OUT/wz-tailscale.tar" \
    deploy/mikrotik/tailscale

echo
ls -lh "$OUT"
echo "Copier ces 2 fichiers dans <clé USB>/wifizone/ sur le routeur."
