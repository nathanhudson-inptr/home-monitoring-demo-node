FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      iw iproute2 procps ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy your Python script
COPY ./src/rssi_channel_scan.py /app/rssi_pandas_scan.py

# Copy the POSIX entrypoint (the one shown above)
COPY entrypoint.sh /app/entrypoint.sh
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Defaults (can be overridden by envs/command)
ENV IFACE=wlan0 \
    INTERVAL=5 \
    OUT=/data/wifi_rssi_log.csv

ENTRYPOINT ["/app/entrypoint.sh"]