#!/usr/bin/env bash
#
# Start the Meshgate server.
#
# Runs preflight checks that catch the common startup failures before the
# server is launched, then hands over to it with exec so signal handling and
# exit codes pass straight through.
#
#   scripts/start.sh                          # auto-detect config and device
#   scripts/start.sh -v                       # debug logging
#   scripts/start.sh -c /etc/meshgate.yaml    # explicit config
#   scripts/start.sh --connection tcp --tcp-host 10.0.0.5
#
# Any arguments are passed through to `meshgate`; see `meshgate --help`.
#
# Options handled by this script (must come first):
#   --no-sync     Skip dependency installation (faster restarts)
#   --check       Run preflight checks and exit without starting
#
# Environment:
#   MESHGATE_CONFIG   Config file path (same as -c)
#   MESHGATE_NO_SYNC  Set to 1 to skip dependency installation

set -euo pipefail

# Resolve the repo root from this script's location, so the script works from
# any working directory (including a systemd unit with no WorkingDirectory).
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
cd "${REPO_ROOT}"

NO_SYNC="${MESHGATE_NO_SYNC:-0}"
CHECK_ONLY=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-sync) NO_SYNC=1; shift ;;
        --check)   CHECK_ONLY=1; shift ;;
        *)         break ;;
    esac
done

# Remaining arguments go to the server verbatim.
ARGS=("$@")

log()  { printf '\033[0;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[0;33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[0;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# --- uv -----------------------------------------------------------------

if ! command -v uv >/dev/null 2>&1; then
    die "uv is not installed or not on PATH.
  Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh
  Then re-run this script."
fi

# --- config -------------------------------------------------------------

# Mirrors the search order in meshgate.cli.load_config. Resolved here only so
# the script can inspect settings and report which file is in use; the path is
# passed through explicitly so both agree on the answer.
CONFIG_PATH=""

# An explicit -c/--config in ARGS wins and is left for the server to handle.
for i in "${!ARGS[@]}"; do
    case "${ARGS[$i]}" in
        -c|--config)
            CONFIG_PATH="${ARGS[$((i + 1))]:-}"
            [[ -n "${CONFIG_PATH}" ]] || die "-c/--config given with no path"
            ;;
    esac
done

if [[ -z "${CONFIG_PATH}" && -n "${MESHGATE_CONFIG:-}" ]]; then
    CONFIG_PATH="${MESHGATE_CONFIG}"
    ARGS=(-c "${CONFIG_PATH}" "${ARGS[@]+"${ARGS[@]}"}")
fi

if [[ -z "${CONFIG_PATH}" ]]; then
    for candidate in \
        "${REPO_ROOT}/config.yaml" \
        "${REPO_ROOT}/config.yml" \
        "${HOME}/.config/meshtastic-handler/config.yaml"
    do
        if [[ -f "${candidate}" ]]; then
            CONFIG_PATH="${candidate}"
            break
        fi
    done
fi

if [[ -n "${CONFIG_PATH}" ]]; then
    [[ -f "${CONFIG_PATH}" ]] || die "config file not found: ${CONFIG_PATH}"
    [[ -r "${CONFIG_PATH}" ]] || die "config file is not readable: ${CONFIG_PATH}"
    log "Config: ${CONFIG_PATH}"
else
    log "Config: none found, using built-in defaults"
    if [[ -f "${REPO_ROOT}/config.sample.yaml" ]]; then
        echo "    (copy config.sample.yaml to config.yaml to customize)"
    fi
fi

# --- dependencies -------------------------------------------------------

if [[ "${NO_SYNC}" == "1" ]]; then
    log "Skipping dependency sync (--no-sync)"
else
    log "Installing dependencies"
    # --inexact so a plain sync does not uninstall anything extra already in
    # the environment. Without it, running this script in a working copy would
    # remove the dev tools (pytest, ruff) that are not runtime dependencies.
    uv sync --quiet --inexact
fi

# Read every setting the preflight needs in one pass. Parsed with pyyaml
# (a core dependency, so present after the base sync) rather than grep, so a
# commented-out or similarly-named nested key is not misread. Values are
# emitted as shell assignments and eval'd - one interpreter start rather than
# one per key.
read_config_vars() {
    uv run --quiet python - "${CONFIG_PATH}" <<'PY' 2>/dev/null || true
import pathlib
import shlex
import sys

import yaml

DEFAULTS = {
    "CFG_CONNECTION": ("meshtastic.connection_type", "serial"),
    "CFG_DEVICE": ("meshtastic.device", ""),
    "CFG_TCP_HOST": ("meshtastic.tcp_host", ""),
    "CFG_WEB_ENABLED": ("web.enabled", False),
    "CFG_WEB_HOST": ("web.host", "127.0.0.1"),
    "CFG_WEB_PORT": ("web.port", 8080),
    "CFG_TRANSCRIPTS": ("web.transcript_enabled", False),
}

path = sys.argv[1] if len(sys.argv) > 1 else ""
data = {}
if path and pathlib.Path(path).is_file():
    data = yaml.safe_load(pathlib.Path(path).read_text()) or {}


def lookup(dotted, default):
    node = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or node.get(part) is None:
            return default
        node = node[part]
    return node


for name, (dotted, default) in DEFAULTS.items():
    value = lookup(dotted, default)
    if isinstance(value, bool):
        value = "1" if value else "0"
    print(f"{name}={shlex.quote(str(value))}")
PY
}

# Defaults, in case the config could not be parsed at all.
CFG_CONNECTION="serial"
CFG_DEVICE=""
CFG_TCP_HOST=""
CFG_WEB_ENABLED="0"
CFG_WEB_HOST="127.0.0.1"
CFG_WEB_PORT="8080"
CFG_TRANSCRIPTS="0"

eval "$(read_config_vars)"

if [[ "${CFG_WEB_ENABLED}" == "1" ]]; then
    if [[ "${NO_SYNC}" != "1" ]]; then
        log "Dashboard enabled, installing web extra"
        uv sync --quiet --inexact --extra web
    fi
    log "Dashboard will listen on http://${CFG_WEB_HOST}:${CFG_WEB_PORT}"

    if [[ "${CFG_WEB_HOST}" != "127.0.0.1" && "${CFG_WEB_HOST}" != "localhost" ]]; then
        warn "dashboard is bound to ${CFG_WEB_HOST}, not loopback. It exposes session
  content and allows plugin and session changes with no authentication."
    fi

    if [[ "${CFG_TRANSCRIPTS}" == "1" ]]; then
        warn "chat transcripts are enabled: the message content of every node
  that talks to this gateway will be recorded in memory."
    fi
fi

# --- radio --------------------------------------------------------------

CONNECTION="${CFG_CONNECTION}"
DEVICE="${CFG_DEVICE}"

# CLI overrides win over the config file.
for i in "${!ARGS[@]}"; do
    case "${ARGS[$i]}" in
        --connection) CONNECTION="${ARGS[$((i + 1))]:-${CONNECTION}}" ;;
        --device)     DEVICE="${ARGS[$((i + 1))]:-${DEVICE}}" ;;
    esac
done

# Serial devices present, via glob rather than parsing ls output.
serial_devices() {
    local found=()
    local candidate
    for candidate in /dev/ttyUSB* /dev/ttyACM*; do
        [[ -e "${candidate}" ]] && found+=("${candidate}")
    done
    printf '%s\n' "${found[@]+"${found[@]}"}"
}

if [[ "${CONNECTION}" == "serial" ]]; then
    if [[ -n "${DEVICE}" ]]; then
        if [[ ! -e "${DEVICE}" ]]; then
            die "serial device not found: ${DEVICE}
  Connected devices: $(serial_devices | tr '\n' ' ')
  Or set meshtastic.device to null to auto-detect."
        fi
        if [[ ! -r "${DEVICE}" || ! -w "${DEVICE}" ]]; then
            # By far the most common cause of a gateway that will not connect.
            die "no read/write permission on ${DEVICE}
  Add yourself to the group that owns it, then log out and back in:
    sudo usermod -aG $(stat -c '%G' "${DEVICE}" 2>/dev/null || echo dialout) \"\$USER\""
        fi
        log "Radio: serial ${DEVICE}"
    else
        FOUND=$(serial_devices | head -1)
        if [[ -z "${FOUND}" ]]; then
            warn "no /dev/ttyUSB* or /dev/ttyACM* device found. Auto-detect will
  probably fail. Plug in the radio, or use --connection tcp."
        else
            log "Radio: serial auto-detect (found ${FOUND})"
        fi
    fi
elif [[ "${CONNECTION}" == "tcp" ]]; then
    TCP_HOST="${CFG_TCP_HOST}"
    for i in "${!ARGS[@]}"; do
        [[ "${ARGS[$i]}" == "--tcp-host" ]] && TCP_HOST="${ARGS[$((i + 1))]:-${TCP_HOST}}"
    done
    [[ -n "${TCP_HOST}" ]] || die "connection is tcp but no tcp_host is set.
  Set meshtastic.tcp_host in the config, or pass --tcp-host."
    log "Radio: tcp ${TCP_HOST}"
else
    log "Radio: ${CONNECTION}"
fi

if [[ "${CHECK_ONLY}" == "1" ]]; then
    log "Preflight checks passed (--check, not starting)"
    exit 0
fi

# --- start --------------------------------------------------------------

log "Starting Meshgate (Ctrl-C to stop)"

# exec, so the server replaces this shell: SIGTERM from systemd or Docker
# reaches it directly and its exit code becomes ours. Without this, signals
# would stop the wrapper and leave the serial port open.
exec uv run --quiet meshgate ${ARGS[@]+"${ARGS[@]}"}
