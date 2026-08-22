#!/usr/bin/env bash
# syncthing-bind-heal.sh — recreate the Syncthing container when its /config
# bind is detached from the real (eCryptfs-mounted) home directory.
#
# Root cause (diagnosed 2026-08-22): on amd-tower, /home/shawn is an
# eCryptfs mount that only appears at login. The Syncthing container has
# `restart: always`, so after a reboot Docker starts it BEFORE login —
# binding the un-mounted underlay path instead of the real config. The
# container then runs a stale default config with the WRONG DEVICE
# IDENTITY, connects to nobody, and syncs nothing, while `docker ps`
# reports it healthy. This is exactly the failure repaired on 2026-08-08
# and re-observed on 2026-08-22: the repair could never stick because
# every reboot re-created the detachment.
#
# Detection is the same inode comparison `syncthing-health.sh` uses; the
# remedy is `docker compose up -d --force-recreate`, which re-resolves the
# bind against the now-mounted home. Run from a systemd USER unit
# (WantedBy=default.target) so it fires at login — i.e. after eCryptfs has
# mounted — on every boot:
#
#   ~/.config/systemd/user/syncthing-bind-heal.service
#   systemctl --user daemon-reload && systemctl --user enable --now \
#       syncthing-bind-heal.service
#
# Safe to run at any time: a healthy container is left untouched. Always
# exits 0 — a heal script must never break a login or a hook chain.

set -uo pipefail

COMPOSE_DIR="$HOME/docker/syncthing"
CONFIG_DIR="$COMPOSE_DIR/config"
CONTAINER="syncthing"

say() { echo "[syncthing-bind-heal] $*" >&2; }

# Not every machine runs the container — absent setup is a silent no-op.
[[ -f "$COMPOSE_DIR/docker-compose.yml" ]] || exit 0
command -v docker >/dev/null 2>&1 || exit 0

# Only act when the REAL config is visible — cert.pem lives in the genuine
# (decrypted) config dir. If it is absent, home is not mounted yet and a
# recreate would just re-bind the underlay: worse than doing nothing.
if [[ ! -f "$CONFIG_DIR/cert.pem" ]]; then
    say "real config not visible (home not mounted?) — refusing to act"
    exit 0
fi

running="$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)"
host_inode="$(stat -c %i "$CONFIG_DIR" 2>/dev/null)"
container_inode="$(docker exec "$CONTAINER" stat -c %i /config 2>/dev/null)"

if [[ "$running" == "true" && -n "$host_inode" && "$host_inode" == "$container_inode" ]]; then
    exit 0  # healthy — bind attached, container up
fi

say "container running=$running host_inode=$host_inode container_inode=${container_inode:-none} — recreating"
if docker compose -f "$COMPOSE_DIR/docker-compose.yml" up -d --force-recreate >&2; then
    say "recreated; bind re-attached"
else
    say "docker compose up FAILED — mesh still down; see syncthing-health gate"
fi
exit 0
