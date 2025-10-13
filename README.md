# home-monitoring-demo-node
A node (Raspberry Pi 3B+) with integrated sensors, used to help monitor home activity discretely. 

### Pre-Requisites
1. RPI Model 3B+ (or later)
2. Download and install Docker (https://forums.docker.com/t/installation-steps-for-the-latest-raspberry-pi-os-64-bit/138838)
3. Download and install Portainer (https://docs.portainer.io/start/install-ce/server/docker/linux)
4. (Optional) SSH Setup with RPi to allow for CLI Remote access to RPI

### Getting Started
1. Create ~/rssi-data/ directory using `mkdir ~/rssi-data/`
2. Create an empty .csv file, `touch ~/rssi-data/wifi_rssi_log.csv`
3. Run `docker run -d \
  --name rssi-logger \
  --pull always \
  --network host \
  --cap-add NET_ADMIN \
  --cap-add NET_RAW \
  --restart unless-stopped \
  -v /home/node1/rssi-data:/data \
  -e TZ=Europe/London \
  -e IFACE=wlan0 \
  -e INTERVAL="5" \
  -e OUT=/data/wifi_rssi_log.csv \
  -e SSID="your-ssid" \
  -e LOCATION="your-location" \
  nathanhudsoninptr/home-monitoring-node:latest`

   *Options: Replace with preferred value or comment out `#` if not used*
   - `"your-ssid"` *Filter by SSID (default: None)*
   - `"node-location"` *Add Location Tag*
4. Or, copy, paste and run the `docker-compose.yml` (found in this repo)

### Monitoring
You can then monitor the .csv output with the following CLI command: `watch -n 1 'wc -l /home/node1/rssi-data/wifi_rssi_log.csv; tail -n 40 /home/node1/rssi-data/wifi_rssi_log.csv'`

This will display the latest 40 entries (logs), these should update periodically (approx. every second) 

Run `docker ps -a` to get the name of and check container is `Up`

Run `sudo docker logs -f [container name]` to display program output
