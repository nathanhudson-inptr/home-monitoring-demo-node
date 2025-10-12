# home-monitoring-demo-node
A node (Raspberry Pi 3B+) with integrated sensors, used to help monitor home activity discretely. 

### Getting Started
1. Download and install Docker (https://forums.docker.com/t/installation-steps-for-the-latest-raspberry-pi-os-64-bit/138838)
2. Download and install Portainer (https://docs.portainer.io/start/install-ce/server/docker/linux)
3. Create /rssi-data/ directory using `mkdir /rssi-data/`
4. Create an empty .csv file, `touch /rssi-data/wifi_rssi_log.csv`
5. On Portainer, create a new stack, copy and paste `docker-compose.yml` (from this repo)
6. Deploy

### Montoring
You can then monitor the .csv output with the following command:
`watch -n 1 'wc -l /home/node1/rssi-data/wifi_rssi_log.csv; tail -n 40 /home/node1/rssi-data/wifi_rssi_log.csv'`
