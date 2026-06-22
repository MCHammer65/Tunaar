#!/bin/sh
# Tunaar deploy/update helper — manage the container without remembering flags.
#
#   ./tunaar.sh up            # pull latest image + (re)start
#   ./tunaar.sh update        # pull latest image, recreate, prune old image
#   ./tunaar.sh logs          # follow logs
#   ./tunaar.sh status        # container + health
#   ./tunaar.sh restart       # restart the container
#   ./tunaar.sh down          # stop and remove the container
#
# Configure via env vars (or edit the defaults below):
#   TUNAAR_PLAYLIST  IPTV playlist URL (only thing you usually need)
#   TUNAAR_EPG_URL   optional XMLTV guide URL
#   TUNAAR_IMAGE     image ref (default ghcr.io/mchammer65/plexiptv:latest)
#   TUNAAR_PORT      host port for the dashboard (default 5004)
#   TUNAAR_VOLUME    named volume for persisted config (default tunaar-config)
#   TUNAAR_NETWORK   "host" (default) or "bridge" (uses -p PORT:5004)

set -eu

IMAGE="${TUNAAR_IMAGE:-ghcr.io/mchammer65/plexiptv:latest}"
NAME="tunaar"
PORT="${TUNAAR_PORT:-5004}"
VOLUME="${TUNAAR_VOLUME:-tunaar-config}"
NETWORK="${TUNAAR_NETWORK:-host}"
PLAYLIST="${TUNAAR_PLAYLIST:-https://iptv-org.github.io/iptv/index.m3u}"

log() { printf '\033[1;33m[tunaar]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[tunaar] %s\033[0m\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "docker not found on PATH"

run_container() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true

  set -- -d --name "$NAME" --restart unless-stopped \
    -e "TUNAAR_PLAYLIST=$PLAYLIST" \
    -v "$VOLUME:/config"
  [ -n "${TUNAAR_EPG_URL:-}" ] && set -- "$@" -e "TUNAAR_EPG_URL=$TUNAAR_EPG_URL"

  if [ "$NETWORK" = "host" ]; then
    set -- "$@" --network host
  else
    set -- "$@" -p "$PORT:5004"
  fi

  log "starting $NAME ($IMAGE, network=$NETWORK)"
  docker run "$@" "$IMAGE" >/dev/null
  log "dashboard: http://<this-host>:$PORT"
}

case "${1:-up}" in
  up)
    log "pulling $IMAGE"
    docker pull "$IMAGE"
    run_container
    ;;
  update)
    log "pulling $IMAGE"
    BEFORE="$(docker images -q "$IMAGE" 2>/dev/null || true)"
    docker pull "$IMAGE"
    AFTER="$(docker images -q "$IMAGE" 2>/dev/null || true)"
    run_container
    if [ -n "$BEFORE" ] && [ "$BEFORE" != "$AFTER" ]; then
      log "removing previous image layer"
      docker image rm "$BEFORE" >/dev/null 2>&1 || true
    fi
    log "update complete"
    ;;
  restart) docker restart "$NAME" >/dev/null && log "restarted" ;;
  down)    docker rm -f "$NAME" >/dev/null 2>&1 && log "removed" || log "not running" ;;
  logs)    exec docker logs -f "$NAME" ;;
  status)
    docker ps --filter "name=$NAME" --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'
    log "health:"
    docker exec "$NAME" python -c \
      "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:5004/healthz').read().decode())" \
      2>/dev/null || log "health check unavailable (container may still be starting)"
    ;;
  *) die "unknown command '$1' (use: up|update|restart|down|logs|status)" ;;
esac
