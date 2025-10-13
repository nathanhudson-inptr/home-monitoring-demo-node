#!/bin/sh

# #!/usr/bin/env bash

# # Disable Wi-Fi power saving on ${IFACE:-wlan0} if available
# if command -v iw >/dev/null 2>&1; then
#   echo "[entrypoint] Disabling Wi-Fi power saving on ${IFACE:-wlan0}"
#   iw dev "${IFACE:-wlan0}" set power_save off || true
# fi

# # Set environment variables for Python script
# set -euo pipefail
# ssid_arg=()
# [[ -n "${SSID:-}" ]] && ssid_arg=(--ssid "$SSID")

# # Run Python script
# exec python3 /app/rssi_pandas_scan.py \
#   --if "${IFACE:-wlan0}" \
#   --interval "${INTERVAL:-5}" \
#   --out "${OUT:-/data/wifi_rssi_log.csv}" \
#   --location "${LOCATION:-}" \
#   "${ssid_arg[@]}"

#-----------------------------------------------------------------------------


# # This was latest

# #!/bin/sh
# set -eu

# # Disable Wi-Fi power saving (needs --cap-add=NET_ADMIN)
# if command -v iw >/dev/null 2>&1; then
#   echo "[entrypoint] Disabling Wi-Fi power saving on ${IFACE:-wlan0}"
#   iw dev "${IFACE:-wlan0}" set power_save off || true
# fi

# # If the container was started with args (e.g. via compose `command:`), pass them straight through
# if [ "$#" -gt 0 ]; then
#   echo "[entrypoint] Using CLI args: $*"
#   exec python3 /app/rssi_pandas_scan.py "$@"
# fi

# # Otherwise, build args from env vars (only include flags that are set)
# set -- \
#   --if "${IFACE:-wlan0}" \
#   --interval "${INTERVAL:-5}" \
#   --out "${OUT:-/data/wifi_rssi_log.csv}"

# [ -n "${SSID:-}" ]     && set -- "$@" --ssid "${SSID}"
# [ -n "${LOCATION:-}" ] && set -- "$@" --location "${LOCATION}"

# exec python3 /app/rssi_pandas_scan.py "$@"


#-----------------------------------------------------------------------------


# #!/bin/sh
set -eu

# Disable Wi-Fi power saving (requires --cap-add=NET_ADMIN)
if command -v iw >/dev/null 2>&1; then
  echo "[entrypoint] Disabling Wi-Fi power saving on ${IFACE:-wlan0}"
  iw dev "${IFACE:-wlan0}" set power_save off || true
fi

# If Compose provided args via `command:`, pass them straight through.
if [ "$#" -gt 0 ]; then
  echo "[entrypoint] Using CLI args: $*"
  exec python3 /app/rssi_pandas_scan.py "$@"
fi

# Otherwise, build args from env variables.
set -- \
  --if "${IFACE:-wlan0}" \
  --interval "${INTERVAL:-5}" \
  --out "${OUT:-/data/wifi_rssi_log.csv}"

[ -n "${SSID:-}" ]     && set -- "$@" --ssid "${SSID}"
[ -n "${LOCATION:-}" ] && set -- "$@" --location "${LOCATION}"

echo "[entrypoint] Using env defaults: $*"
exec python3 /app/rssi_pandas_scan.py "$@"
