# Dockerfile
FROM python:3.11-slim

# System tools needed for scanning and basics
RUN apt-get update && apt-get install -y --no-install-recommends \
      iw iproute2 procps ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

# App files
WORKDIR /app
# (Put your Python script alongside this Dockerfile)
COPY ./src/rssi_pandas_scan.py /app/rssi_pandas_scan.py
COPY ./entrypoint.sh        /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Python deps
RUN pip install --no-cache-dir -r requirements.txt

# Config via env (you can override at `docker run`)
ENV IFACE=wlan0
ENV INTERVAL=5
# We'll write logs to a bind-mounted /data so they persist on the host
ENV OUT=/data/wifi_rssi_log.csv
# Optional: only log a single SSID; leave empty to log all
ENV SSID=

# Run as root so `iw scan` can work (needs netadmin caps). We’ll scope with caps at runtime.
ENTRYPOINT ["/app/entrypoint.sh"]