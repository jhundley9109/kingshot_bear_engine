#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-kingshot-bear-engine}"
LOG_DIR="${LOG_DIR:-/var/log/${SERVICE_NAME}}"
LOG_FILE="${LOG_DIR}/bot.log"
START_SERVICE=true

usage() {
    cat <<'EOF'
Usage: sudo ./scripts/install-systemd.sh [--no-start]

Installs the Python environment, systemd service, and log rotation config.

Environment overrides:
  SERVICE_USER   Linux user that will run the bot (default: invoking user/repo owner)
  SERVICE_NAME   systemd service name (default: kingshot-bear-engine)
  LOG_DIR        log directory (default: /var/log/<service-name>)
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-start)
            START_SERVICE=false
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "This installer requires Linux with systemd." >&2
    exit 1
fi

if [[ $EUID -ne 0 ]]; then
    echo "Run this installer as root: sudo $0" >&2
    exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
SERVICE_NAME="${SERVICE_NAME:-kingshot-bear-engine}"
LOG_DIR="${LOG_DIR:-/var/log/${SERVICE_NAME}}"
LOG_FILE="${LOG_DIR}/bot.log"

if [[ ! "$SERVICE_NAME" =~ ^[A-Za-z0-9_.@-]+$ ]]; then
    echo "SERVICE_NAME contains unsupported characters: $SERVICE_NAME" >&2
    exit 1
fi

if [[ ! -f "${PROJECT_DIR}/bot.py" || ! -f "${PROJECT_DIR}/requirements.txt" ]]; then
    echo "Could not find bot.py and requirements.txt in ${PROJECT_DIR}." >&2
    exit 1
fi

if [[ ! -f "${PROJECT_DIR}/.env" ]]; then
    echo "Create ${PROJECT_DIR}/.env before installing the service." >&2
    exit 1
fi

for command_name in systemctl python3 runuser install sed; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "Required command is missing: $command_name" >&2
        exit 1
    fi
done

repo_owner="$(stat -c '%U' "$PROJECT_DIR")"
SERVICE_USER="${SERVICE_USER:-${SUDO_USER:-$repo_owner}}"
if [[ "$SERVICE_USER" == "root" && "$repo_owner" != "root" ]]; then
    SERVICE_USER="$repo_owner"
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    echo "Service user does not exist: $SERVICE_USER" >&2
    exit 1
fi
SERVICE_GROUP="$(id -gn "$SERVICE_USER")"

if [[ ! -d "${PROJECT_DIR}/venv" ]]; then
    echo "Creating Python virtual environment..."
    runuser -u "$SERVICE_USER" -- python3 -m venv "${PROJECT_DIR}/venv"
fi

echo "Installing Python dependencies..."
runuser -u "$SERVICE_USER" -- "${PROJECT_DIR}/venv/bin/python" -m pip install -r "${PROJECT_DIR}/requirements.txt"

install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_GROUP" "${PROJECT_DIR}/data"
install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_GROUP" "${PROJECT_DIR}/data/.matplotlib"
install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_GROUP" "$LOG_DIR"
if [[ ! -e "$LOG_FILE" ]]; then
    install -m 0640 -o "$SERVICE_USER" -g "$SERVICE_GROUP" /dev/null "$LOG_FILE"
else
    chown "$SERVICE_USER:$SERVICE_GROUP" "$LOG_FILE"
    chmod 0640 "$LOG_FILE"
fi
chown "$SERVICE_USER:$SERVICE_GROUP" "${PROJECT_DIR}/.env"
chmod 0600 "${PROJECT_DIR}/.env"

escape_sed_replacement() {
    printf '%s' "$1" | sed 's/[&|\\]/\\&/g'
}

project_replacement="$(escape_sed_replacement "$PROJECT_DIR")"
user_replacement="$(escape_sed_replacement "$SERVICE_USER")"
group_replacement="$(escape_sed_replacement "$SERVICE_GROUP")"
log_dir_replacement="$(escape_sed_replacement "$LOG_DIR")"
log_file_replacement="$(escape_sed_replacement "$LOG_FILE")"

unit_tmp="$(mktemp)"
logrotate_tmp="$(mktemp)"
trap 'rm -f "$unit_tmp" "$logrotate_tmp"' EXIT

sed \
    -e "s|@PROJECT_DIR@|${project_replacement}|g" \
    -e "s|@SERVICE_USER@|${user_replacement}|g" \
    -e "s|@SERVICE_GROUP@|${group_replacement}|g" \
    -e "s|@LOG_DIR@|${log_dir_replacement}|g" \
    -e "s|@LOG_FILE@|${log_file_replacement}|g" \
    "${PROJECT_DIR}/deploy/kingshot-bear-engine.service.in" > "$unit_tmp"

sed \
    -e "s|@SERVICE_USER@|${user_replacement}|g" \
    -e "s|@SERVICE_GROUP@|${group_replacement}|g" \
    -e "s|@LOG_FILE@|${log_file_replacement}|g" \
    "${PROJECT_DIR}/deploy/kingshot-bear-engine.logrotate.in" > "$logrotate_tmp"

install -m 0644 "$unit_tmp" "/etc/systemd/system/${SERVICE_NAME}.service"
install -m 0644 "$logrotate_tmp" "/etc/logrotate.d/${SERVICE_NAME}"

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service"

if [[ "$START_SERVICE" == true ]]; then
    systemctl restart "${SERVICE_NAME}.service"
    echo
    systemctl --no-pager --full status "${SERVICE_NAME}.service" || true
else
    echo "Service installed and enabled; it was not started (--no-start)."
fi

echo
echo "Installed ${SERVICE_NAME}.service"
echo "Logs:    ${LOG_FILE}"
echo "Follow:  tail -f ${LOG_FILE}"
echo "Status:  sudo systemctl status ${SERVICE_NAME}"
echo "Restart: sudo systemctl restart ${SERVICE_NAME}"
