#!/usr/bin/env bash
# make_video.sh: record the Rebuttal demo video from the running app.
#
# What it does, in order:
#   1. Preflight: checks the tools (macOS say, ffmpeg, ffprobe, node, npm, npx, uv, curl, lsof) and that
#      ports 8100 (backend) and 4273 (frontend) are free.
#   2. Clears the previous take's files from media/work/ (files only).
#   3. Writes the narration and runs the real pytest checks for the terminal card. A failing test fails the take.
#   4. Builds the frontend against the local backend and serves it with vite preview.
#   5. Starts a fresh backend in mock mode with the rules reasoner and no secrets, then checks its health.
#   6. Records the browser walkthrough with Playwright and assembles media/rebuttal-demo.mp4 with ffmpeg.
#   7. Prints the output path and duration, and fails if the video is 3 minutes or longer.
#   Both servers are stopped on exit, including after a failure, so the ports are free for the next take.
#
# Usage: scripts/make_video.sh
#
# Free tooling only: macOS say, ffmpeg (brew install ffmpeg), Node.js, uv and lsof. No paid API and no keys.
# The backend gets an empty value for every secret it reads, so no key from backend/.env reaches it.
#
# Output: media/rebuttal-demo.mp4 (media/ is git-ignored). Intermediate files are in media/work/.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$ROOT/media/work"
OUT="$ROOT/media/rebuttal-demo.mp4"
BACKEND_PORT=8100
APP_PORT=4273
BACKEND_PID=""
VITE_PID=""

die() {
  echo "make_video: $*" >&2
  exit 1
}

# Stops a background process and the children it started (npx and uv run each start their own process).
stop_tree() {
  local pid="$1" child
  [ -n "$pid" ] || return 0
  while read -r child; do
    stop_tree "$child"
  done < <(pgrep -P "$pid" 2>/dev/null || true)
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
}

cleanup() {
  trap - EXIT
  stop_tree "$VITE_PID"
  stop_tree "$BACKEND_PID"
}
trap cleanup EXIT
# Ctrl-C or a TERM stops the take: exiting runs cleanup once through the EXIT trap, so both servers stop.
trap 'exit 130' INT
trap 'exit 143' TERM

for tool in ffmpeg ffprobe say node npm npx uv curl lsof; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    case "$tool" in
      ffmpeg | ffprobe) die "$tool is not installed. Install it with: brew install ffmpeg" ;;
      say) die "say is not available. This script needs macOS (say)." ;;
      *) die "$tool is not installed." ;;
    esac
  fi
done

check_port_free() {
  local port="$1"
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    die "port $port is already in use. Stop the process listening on it (lsof -nP -iTCP:$port -sTCP:LISTEN shows which), then rerun. A stale server would invalidate the take."
  fi
}
check_port_free "$BACKEND_PORT"
check_port_free "$APP_PORT"

mkdir -p "$WORK"
find "$WORK" -type f -delete

(cd "$ROOT/backend" && uv run python -m scripts.video_assemble narrate --shots ../frontend/video/shots.json --work "$WORK")

# Real test output for the terminal card. The exit status is kept: a failing test fails the take.
if ! (cd "$ROOT/backend" && uv run pytest tests/test_write_boundary.py "tests/test_core.py::test_analyze_never_writes_to_paypal" -v --color=no) > "$WORK/pytest.txt" 2>&1; then
  cat "$WORK/pytest.txt"
  die "pytest failed; the output is above and in $WORK/pytest.txt"
fi

[ -d "$ROOT/frontend/node_modules" ] || (cd "$ROOT/frontend" && npm ci)
(cd "$ROOT/frontend" && VITE_API_BASE="http://localhost:$BACKEND_PORT" VITE_API_TOKEN= npm run build)
# The preflight check ran minutes ago, so check again right before each server starts.
check_port_free "$APP_PORT"
(cd "$ROOT/frontend" && exec npx vite preview --port "$APP_PORT" --strictPort) > "$WORK/vite.log" 2>&1 &
VITE_PID=$!

check_port_free "$BACKEND_PORT"
# A fresh backend per take is required: the mock is in memory, so a reused server would keep the last take's disputes.
# Every secret is forced empty so that no key from backend/.env reaches this process.
(
  cd "$ROOT/backend" && exec env \
    REBUTTAL_MOCK=1 \
    REBUTTAL_REASONER=rules \
    REBUTTAL_TRACING=0 \
    REBUTTAL_ALLOW_OPEN_API=1 \
    REBUTTAL_API_TOKEN= \
    REBUTTAL_PROVIDER= \
    REBUTTAL_CHECKPOINT_URL= \
    DATABASE_URL= \
    REBUTTAL_AUDIT_PATH="$WORK/audit.jsonl" \
    REBUTTAL_CORS_ORIGINS="http://localhost:$APP_PORT" \
    PAYPAL_CLIENT_ID= \
    PAYPAL_CLIENT_SECRET= \
    PAYPAL_WEBHOOK_ID= \
    GROQ_API_KEY= \
    ANTHROPIC_API_KEY= \
    NVIDIA_API_KEY= \
    LANGFUSE_PUBLIC_KEY= \
    LANGFUSE_SECRET_KEY= \
    LANGFUSE_HOST= \
    SUPABASE_ACCESS_TOKEN= \
    PAYPAL_BUYER_CLIENT_ID= \
    PAYPAL_BUYER_CLIENT_SECRET= \
    uv run uvicorn rebuttal.app:app --port "$BACKEND_PORT"
) > "$WORK/backend.log" 2>&1 &
BACKEND_PID=$!

deadline=$((SECONDS + 60))
until curl -fs "http://localhost:$BACKEND_PORT/api/health" >/dev/null 2>&1 && curl -fs "http://localhost:$APP_PORT/" >/dev/null 2>&1; do
  kill -0 "$VITE_PID" 2>/dev/null || die "vite exited early; see $WORK/vite.log"
  kill -0 "$BACKEND_PID" 2>/dev/null || die "backend exited early; see $WORK/backend.log"
  [ "$SECONDS" -lt "$deadline" ] || die "backend and frontend did not both answer within 60 s; see $WORK/backend.log and $WORK/vite.log"
  sleep 1
done

health="$(curl -fs "http://localhost:$BACKEND_PORT/api/health")"
if ! grep -Eq '"mode"[[:space:]]*:[[:space:]]*"mock / rules"' <<< "$health"; then
  die "backend is not in mock mode with the rules reasoner: $health"
fi

(cd "$ROOT/frontend" && VIDEO_WORK_DIR="$WORK" VIDEO_BASE_URL="http://localhost:$APP_PORT" npx playwright test -c video/playwright.config.ts)

(cd "$ROOT/backend" && uv run python -m scripts.video_assemble assemble --shots ../frontend/video/shots.json --work "$WORK" --out "$OUT")

duration_s="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$OUT")"
whole_s="${duration_s%.*}"
clock="$((whole_s / 60)):$(printf '%02d' $((whole_s % 60)))"
echo "Wrote $OUT (duration $clock)"
if [ "$whole_s" -ge 180 ]; then
  die "video is $clock long; it must stay under 3:00"
fi
