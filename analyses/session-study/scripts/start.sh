#!/bin/bash
# Starts everything behind one HTTPS address:
#   https://$PUBLIC_IP:26260/                      -> WebRTC rPPG demo
#   https://$PUBLIC_IP:26260/datacollection/       -> data collection study
#   https://$PUBLIC_IP:26260/datacollection/admin  -> operator panel
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
RPPG=${RPPG:-/workspace/hackyeah/HackYeach-2026-REPO}
export PUBLIC_IP=${PUBLIC_IP:-179.255.106.231}
export PUBLIC_PORT=10100 API_PORT=8000 WEBRTC_PORT=10101
export CERT=$RPPG/certs/cert.pem KEY=$RPPG/certs/key.pem

trap 'trap - EXIT; kill 0' EXIT INT TERM

mkdir -p "$RPPG/certs"
if [[ ! -s $CERT || ! -s $KEY ]]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 365 -keyout "$KEY" -out "$CERT" \
    -subj "/CN=$PUBLIC_IP" -addext "subjectAltName=IP:$PUBLIC_IP,IP:127.0.0.1,DNS:localhost"
  chmod 600 "$KEY"
fi
# webrtc_server.py reads the TURN secret at startup, so it must exist first.
[[ -s $RPPG/certs/turn_secret ]] || { openssl rand -hex 32 > "$RPPG/certs/turn_secret"; chmod 600 "$RPPG/certs/turn_secret"; }

echo "== Building frontend"
. /opt/nvm/nvm.sh >/dev/null
(cd "$REPO/web" && { [[ -d node_modules ]] || npm install; } && npm run build)

if [[ ! -x $REPO/server/.venv/bin/uvicorn ]]; then
  python3 -m venv "$REPO/server/.venv"
  "$REPO/server/.venv/bin/pip" install -r "$REPO/server/requirements.txt"
fi

run() {
  local name=$1; shift
  "$@" 2>&1 | sed -u "s/^/[$name] /" &
}

run turn bash "$RPPG/start_turn.sh"
run api env -C "$REPO/server" "$REPO/server/.venv/bin/uvicorn" app:app --host 127.0.0.1 --port $API_PORT --proxy-headers
run webrtc env -C "$RPPG" /venv/main/bin/python webrtc_server.py --host 127.0.0.1 --port $WEBRTC_PORT --no-ssl
run caddy caddy run --adapter caddyfile --config "$REPO/scripts/Caddyfile"

echo "== Ready (Ctrl+C stops everything)"
echo "   WebRTC demo:      https://$PUBLIC_IP:26260/"
echo "   Data collection:  https://$PUBLIC_IP:26260/datacollection/"
echo "   Operator panel:   https://$PUBLIC_IP:26260/datacollection/admin"
wait -n
