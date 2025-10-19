#!/bin/sh

set -eu

# Disable Wi-Fi power saving if possible (needs --cap-add=NET_ADMIN)
if command -v iw >/dev/null 2>&1; then
  echo "[entrypoint] Disabling Wi-Fi power saving on ${IFACE:-wlan0}"
  iw dev "${IFACE:-wlan0}" set power_save off || true
fi

# Build argument list dynamically from environment variables
set -- \
  --if "${IFACE:-wlan0}" \
  --interval "${INTERVAL:-4}" \
  --timeout "${TIMEOUT:-3.5}" \
  --out "${OUT:-/data/wifi_rssi_log.csv}"

[ -n "${TARGETS:-}" ]     && set -- "$@" --targets "${TARGETS}"
[ -n "${LOCATION:-}" ]    && set -- "$@" --location "${LOCATION}"
[ -n "${FULL_SCAN_MINS:-}" ] && set -- "$@" --full-scan-mins "${FULL_SCAN_MINS}"
[ -n "${FLUSH_EVERY:-}" ]   && set -- "$@" --flush-every "${FLUSH_EVERY}"
[ -n "${NODE_ID:-}" ]     && set -- "$@" --node-id "${NODE_ID}"

echo "[entrypoint] Starting RSSI logger with args: $*"

# Run Python scanner
exec python3 /app/rssi_pandas_scan.py "$@"



# set -eu

# # Disable Wi-Fi power saving (requires --cap-add=NET_ADMIN)
# if command -v iw >/dev/null 2>&1; then
#   echo "[entrypoint] Disabling Wi-Fi power saving on ${IFACE:-wlan0}"
#   iw dev "${IFACE:-wlan0}" set power_save off || true
# fi

# # If Compose provided args via `command:`, pass them straight through.
# if [ "$#" -gt 0 ]; then
#   echo "[entrypoint] Using CLI args: $*"
#   exec python3 /app/rssi_pandas_scan.py "$@"
# fi

# # Otherwise, build args from env variables.
# set -- \
#   --if "${IFACE:-wlan0}" \
#   --interval "${INTERVAL:-5}" \
#   --out "${OUT:-/data/wifi_rssi_log.csv}"

# [ -n "${SSID:-}" ]     && set -- "$@" --ssid "${SSID}"
# [ -n "${LOCATION:-}" ] && set -- "$@" --location "${LOCATION}"

# echo "[entrypoint] Using env defaults: $*"
# exec python3 /app/rssi_pandas_scan.py "$@"
