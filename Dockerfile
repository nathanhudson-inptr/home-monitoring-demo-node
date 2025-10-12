# Dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Minimal tools needed for scanning
RUN apt-get update && apt-get install -y --no-install-recommends \
      iw iproute2 procps ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Create entrypoint directly in the image (avoids CRLF + missing file issues)
RUN set -euo pipefail; cat > /app/entrypoint.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
ssid_arg=()
[[ -n "${SSID:-}" ]] && ssid_arg=(--ssid "$SSID")

exec python3 /app/rssi_pandas_scan.py \
  --if "${IFACE:-wlan0}" \
  --interval "${INTERVAL:-2}" \
  --out "${OUT:-/data/wifi_rssi_log.csv}" \
  "${ssid_arg[@]}"
SH
RUN chmod +x /app/entrypoint.sh

# --- Copy your Python script
COPY ./src/rssi_channel_scan.py /app/rssi_pandas_scan.py

# --- Install deps (split so pandas errors are obvious)
#RUN pip install --no-cache-dir pandas

# Default env (override at runtime)
ENV IFACE=wlan0 \
    INTERVAL=2 \
    OUT=/data/wifi_rssi_log.csv

ENTRYPOINT ["/app/entrypoint.sh"]