#!/bin/sh
# Entrypoint du container Tailscale WIFIZONE.
#
# Variables (définies côté RouterOS dans /container envs, liste wz-ts) :
#   TS_AUTHKEY         clé d'authentification Tailscale (obligatoire au 1er démarrage)
#   TS_HOSTNAME        nom de la machine dans le tailnet (ex. wz-site-a)
#   WZ_FORWARD_TARGET  ip:port du container agent (ex. 172.31.0.3:9001)
#   WZ_FORWARD_PORT    port exposé sur le tailnet (défaut : 9001)
set -eu

# Valeurs par défaut adaptées à RouterOS
export TS_USERSPACE="${TS_USERSPACE:-true}"
export TS_STATE_DIR="${TS_STATE_DIR:-/var/lib/tailscale}"
export TS_AUTH_ONCE="${TS_AUTH_ONCE:-true}"
export TS_SOCKS5_SERVER="${TS_SOCKS5_SERVER:-:1055}"

# Forward TCP tailnet -> agent (config "serve", format ipn.ServeConfig)
if [ -n "${WZ_FORWARD_TARGET:-}" ]; then
    FORWARD_PORT="${WZ_FORWARD_PORT:-9001}"
    cat > /tmp/serve.json <<EOF
{"TCP":{"${FORWARD_PORT}":{"TCPForward":"${WZ_FORWARD_TARGET}"}}}
EOF
    export TS_SERVE_CONFIG=/tmp/serve.json
    echo "[wz-ts] forward tailnet:${FORWARD_PORT} -> ${WZ_FORWARD_TARGET}"
fi

exec /usr/local/bin/containerboot
