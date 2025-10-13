#!/usr/bin/env bash

# Disable Wi-Fi power saving on ${IFACE:-wlan0} if available
if command -v iw >/dev/null 2>&1; then
  echo "[entrypoint] Disabling Wi-Fi power saving on ${IFACE:-wlan0}"
  iw dev "${IFACE:-wlan0}" set power_save off || true
fi

# Set environment variables for Python script
set -euo pipefail
ssid_arg=()
[[ -n "${SSID:-}" ]] && ssid_arg=(--ssid "$SSID")

# Run Python script with arguments
#   --if "${IFACE:-wlan0}": Wi-Fi interface to use for scanning
#   --interval "${INTERVAL:-5}": Interval between scans in seconds
#   --out "${OUT:-/data/wifi_rssi_log.csv}": Output file for the scan results
#   "${ssid_arg[@]}": Optional filter by SSID
exec python3 /app/rssi_pandas_scan.py \
  --if "${IFACE:-wlan0}" \
  --interval "${INTERVAL:-5}" \
  --out "${OUT:-/data/wifi_rssi_log.csv}" \
  "${ssid_arg[@]}"

