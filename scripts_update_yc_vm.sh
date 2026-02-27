#!/usr/bin/env bash
set -euo pipefail

# Update an already deployed bot on Linux VM.
#
# Usage:
#   ./scripts_update_yc_vm.sh /opt/audio-generator-bot tg-audio-bot
#   ./scripts_update_yc_vm.sh /opt/audio-generator-bot tg-audio-bot main
#
# Args:
#   1 - absolute path to git repo on VM
#   2 - systemd service name
#   3 - git branch to deploy (optional, default: current branch)

if [[ "${1:-}" == "" || "${2:-}" == "" ]]; then
  echo "Usage: $0 <repo_path> <systemd_service_name> [branch]"
  exit 1
fi

REPO_PATH="$1"
SERVICE_NAME="$2"
TARGET_BRANCH="${3:-}"

if [[ ! -d "$REPO_PATH/.git" ]]; then
  echo "Error: $REPO_PATH is not a git repository"
  exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "Error: systemctl not found. This script expects a systemd-based VM."
  exit 1
fi

cd "$REPO_PATH"

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ -z "$TARGET_BRANCH" ]]; then
  TARGET_BRANCH="$CURRENT_BRANCH"
fi

echo "Repository: $REPO_PATH"
echo "Service: $SERVICE_NAME"
echo "Deploy branch: $TARGET_BRANCH"
echo "Current commit: $(git rev-parse --short HEAD)"

echo "[1/8] Fetching updates from origin..."
git fetch --all --prune

echo "[2/8] Switching to branch $TARGET_BRANCH ..."
git checkout "$TARGET_BRANCH"

echo "[3/8] Pulling latest changes (fast-forward only)..."
git pull --ff-only origin "$TARGET_BRANCH"

echo "[4/8] Ensuring virtual environment exists..."
if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "[5/8] Upgrading pip..."
python -m pip install --upgrade pip

echo "[6/8] Installing dependencies..."
pip install -r requirements.txt

echo "[7/8] Restarting service $SERVICE_NAME ..."
sudo systemctl restart "$SERVICE_NAME"

echo "[8/8] Checking service status..."
sudo systemctl status "$SERVICE_NAME" --no-pager -l

echo "New commit: $(git rev-parse --short HEAD)"
echo "Deployment update complete."
