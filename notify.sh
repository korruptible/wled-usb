#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'TXT'
Usage: notify.sh <application> [titre] [motif]

  application  nom affiché dans le journal, et clé des règles (ex. Slack, CI)
  titre        texte court, facultatif
  motif        force un motif : slack, message, urgent, call, info

Exemples :
  notify.sh CI "build cassé" urgent
  notify.sh Slack "nouveau message"
  make test || notify.sh Tests "échec" urgent
TXT
  exit 2
}

[ $# -ge 1 ] || usage
[ "$1" = "-h" ] || [ "$1" = "--help" ] && usage

HOST="${WLED_USB_URL:-http://127.0.0.1:8723}"
printf -v BODY '{"app":%s,"title":%s,"pattern":%s}' \
  "$(printf '%s' "$1" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" \
  "$(printf '%s' "${2:-}" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" \
  "$(printf '%s' "${3:-}" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"

curl -sS --max-time 10 -X POST "$HOST/bridge/notify" \
     -H 'Content-Type: application/json' -d "$BODY"
echo
