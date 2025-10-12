#!/usr/bin/env bash


# This script is used to run the RSSI channel scanning script
# It takes the following environment variables:
#   - IFACE: The Wi-Fi interface to use for scanning, default is "wlan0"
#   - INTERVAL: The interval between scans in seconds, default is 5
#   - OUT: The file to write the log to, default is "/data/wifi_rssi_log.csv"
#   - SSID: The optional SSID to log, if not provided all networks will be logged


set -euo pipefail
ssid_arg=()
[[ -n "${SSID:-}" ]] && ssid_arg=(--ssid "$SSID")

exec python3 /app/rssi_pandas_scan.py \
  --if "${IFACE:-wlan0}" \
  --interval "${INTERVAL:-5}" \
  --out "${OUT:-/data/wifi_rssi_log.csv}" \
  "${ssid_arg[@]}"

