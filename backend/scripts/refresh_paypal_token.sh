#!/usr/bin/env bash
# Refresh the PayPal sandbox access token used by the PayPal AI Toolkit MCP server.
#
#   backend/scripts/refresh_paypal_token.sh
#
# Reads PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET from backend/.env, asks the PayPal SANDBOX for a
# client-credentials token, and stores it as PAYPAL_SANDBOX_ACCESS_TOKEN in .claude/settings.local.json
# (git-ignored). The token is never printed. It expires in up to ~9 hours; quit and reopen Claude Code
# afterwards so the MCP server picks up the new value.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$ROOT/backend/.env"
SETTINGS="$ROOT/.claude/settings.local.json"
SANDBOX_TOKEN_URL="https://api-m.sandbox.paypal.com/v1/oauth2/token"  # sandbox only, on purpose

get() { grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//'; }

[ -f "$ENV_FILE" ] || { echo "Missing $ENV_FILE" >&2; exit 1; }
[ "$(get PAYPAL_ENV)" = "sandbox" ] || [ -z "$(get PAYPAL_ENV)" ] || { echo "PAYPAL_ENV must be sandbox" >&2; exit 1; }
CLIENT_ID="$(get PAYPAL_CLIENT_ID)"; CLIENT_SECRET="$(get PAYPAL_CLIENT_SECRET)"
[ -n "$CLIENT_ID" ] && [ -n "$CLIENT_SECRET" ] || { echo "PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET not set in $ENV_FILE" >&2; exit 1; }

# Credentials go to curl on stdin, not argv, so they don't show up in `ps`.
RESPONSE="$(printf 'user = "%s:%s"\n' "$CLIENT_ID" "$CLIENT_SECRET" |
  curl -sS --config - -X POST "$SANDBOX_TOKEN_URL" -d "grant_type=client_credentials")"

mkdir -p "$(dirname "$SETTINGS")"
RESPONSE="$RESPONSE" SETTINGS="$SETTINGS" python3 - <<'PY'
import json, os, sys, time

try:
    data = json.loads(os.environ["RESPONSE"])
    token = data["access_token"]
except (ValueError, KeyError):
    sys.exit("PayPal did not return a token (check the sandbox client ID and secret).")
if "\n" in token or "\r" in token:
    sys.exit("Token contains a newline; refusing to store it.")

path = os.environ["SETTINGS"]
try:
    settings = json.load(open(path))
except (FileNotFoundError, ValueError):
    settings = {}
settings.setdefault("env", {})["PAYPAL_SANDBOX_ACCESS_TOKEN"] = token
with open(path, "w") as fh:
    json.dump(settings, fh, indent=2)
os.chmod(path, 0o600)
hours = int(data.get("expires_in", 0)) / 3600
print(f"Stored PAYPAL_SANDBOX_ACCESS_TOKEN in {path} (expires in about {hours:.1f}h). "
      "Quit and reopen Claude Code to load it.")
PY
