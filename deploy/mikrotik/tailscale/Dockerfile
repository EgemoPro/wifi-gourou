# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────────────────────────────────────
#  Tailscale (image officielle) + un petit entrypoint qui :
#    - garde le mode userspace (aucun /dev/net/tun, aucun iptables : robuste sur RouterOS)
#    - expose un proxy SOCKS5 sortant (l'agent s'en sert pour joindre le central)
#    - transfère le port de commande Tailscale -> container agent (central -> agent)
# ─────────────────────────────────────────────────────────────────────────────
ARG TS_VERSION=v1.104.1
FROM tailscale/tailscale:${TS_VERSION}

COPY ts-entrypoint.sh /usr/local/bin/wz-ts-entrypoint.sh
RUN chmod +x /usr/local/bin/wz-ts-entrypoint.sh

# CMD [] : on annule le CMD hérité de l'image officielle, l'entrypoint lance containerboot
ENTRYPOINT ["/usr/local/bin/wz-ts-entrypoint.sh"]
CMD []
