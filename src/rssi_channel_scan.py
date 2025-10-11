import csv, os, re, subprocess, time, argparse, shutil
from datetime import datetime

# Regular Expressions used to parse output of iwlist command
# BSS_RE: Matches BSS lines containing MAC addresses
BSS_RE = re.compile(r"^BSS ([0-9a-f:]{17})")
# SIG_RE: Matches signal strength lines containing dBm values
SIG_RE = re.compile(r"^\s*signal:\s*(-?\d+(?:\.\d+)?) dBm")
# FREQ_RE: Matches frequency lines containing MHz values
FREQ_RE = re.compile(r"^\s*freq:\s*(\d+)")
# SSID_RE: Matches SSID lines containing network names
SSID_RE = re.compile(r"^\s*SSID:\s*(.*)")

def freq_to_channel(freq_mhz:int) -> int | None:
    """
    Convert a frequency in MHz to a Wi-Fi channel number.

    This function uses the following channel to frequency mappings:
    - 2.4 GHz band: channels 1-14, frequencies 2412-2472 MHz
    - 5 GHz band: channels 36-180, frequencies 5000-5900 MHz
    - Channel 14: frequency 2484 MHz

    Args:
        freq_mhz: The frequency in MHz to convert.

    Returns:
        The corresponding Wi-Fi channel number, or None if no mapping exists.
    """
    if 2412 <= freq_mhz <= 2472:
        return (freq_mhz - 2407) // 5
    if freq_mhz == 2484:
        return 14
    if 5000 <= freq_mhz <= 5900:
        return (freq_mhz - 5000) // 5
    return None

def scan_wifi(interface="wlan0"):
    """
    Scan for Wi-Fi networks using the iwlist command.

    Args:
        interface: The Wi-Fi interface to use for scanning, default is "wlan0".

    Returns:
        A list of dictionaries containing the parsed Wi-Fi network information.
        Each dictionary will contain the following keys:
            - "bssid": The MAC address of the Wi-Fi network.
            - "ssid": The network name of the Wi-Fi network.
            - "signal_dbm": The signal strength of the Wi-Fi network in dBm.
            - "freq_mhz": The frequency of the Wi-Fi network in MHz.
            - "channel": The Wi-Fi channel number of the network, if a mapping exists.
    """
    cmd = ["iw", "dev", interface, "scan"]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout.splitlines()

    results, block = [], []
    for line in out:
        if BSS_RE.match(line):
            if block:
                results.append(parse_block(block))
                block = []
        block.append(line)
    if block:
        results.append(parse_block(block))
    return results

def parse_block(block_lines):
    """
    Parse a block of output from the iwlist command into a dictionary
    containing Wi-Fi network information.

    Args:
        block_lines: A list of lines from the output of the iwlist
            command, representing a single block of a Wi-Fi network.

    Returns:
        A dictionary containing the parsed Wi-Fi network information.
        The dictionary will contain the following keys:
            - "bssid": The MAC address of the Wi-Fi network.
            - "ssid": The network name of the Wi-Fi network.
            - "signal_dbm": The signal strength of the Wi-Fi network in dBm.
            - "freq_mhz": The frequency of the Wi-Fi network in MHz.
            - "channel": The Wi-Fi channel number of the network, if a mapping exists.

    """
    rec = {"bssid": None, "ssid": None, "signal_dbm": None, "freq_mhz": None}
    # Iterate over the lines of the block
    for line in block_lines:
        # Match the line against the appropriate regular expression
        # and update the corresponding key in the dictionary
        if m := BSS_RE.match(line):
            rec["bssid"] = m.group(1).lower()
        elif m := SIG_RE.match(line):
            rec["signal_dbm"] = float(m.group(1))
        elif m := FREQ_RE.match(line):
            rec["freq_mhz"] = int(m.group(1))
        elif m := SSID_RE.match(line):
            rec["ssid"] = m.group(1)
    
    # If the frequency was found, calculate the Wi-Fi channel number
    # and add it to the dictionary
    if rec["freq_mhz"]:
        rec["channel"] = freq_to_channel(rec["freq_mhz"])
    
    # Return the parsed dictionary
    return rec


def main():
    all_scans = []

    while True:
        timestamp = datetime.now()
        print(f"\n[{timestamp:%H:%M:%S}] Scanning Wi-Fi...")
        records = scan_wifi("wlan0")

        # Turn list of dicts into a pandas DataFrame
        df = pd.DataFrame(records)
        df["timestamp"] = timestamp

        # Keep useful columns
        df = df[["timestamp", "ssid", "bssid", "signal_dbm", "freq_mhz", "channel"]]

        # Append to our full list
        all_scans.append(df)

        # Print a quick summary
        print(df[["ssid", "signal_dbm", "freq_mhz", "channel"]].dropna())

        # (Optional) save to CSV
        df.to_csv("wifi_rssi_log.csv", mode="a", index=False, header=False)

        time.sleep(0.1)  # wait 5 seconds between scans
        print(df.head())

if __name__ == "__main__":
    main()