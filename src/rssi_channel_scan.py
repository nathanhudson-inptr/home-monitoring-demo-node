import asyncio, os, re, csv, sys, signal, argparse
from datetime import datetime
#import pandas as pd
from typing import Dict, List

#----Regular Expressions----#
"""
Regular expressions used to parse output of iwlist command.

BSS_RE: Matches BSS lines containing MAC addresses.
SIG_RE: Matches signal strength lines containing dBm values.
FREQ_RE: Matches frequency lines containing MHz values.
SSID_RE: Matches SSID lines containing network names.
"""
BSS_RE = re.compile(r"^BSS ([0-9a-f:]{17})")
SIG_RE = re.compile(r"^\s*signal:\s*(-?\d+(?:\.\d+)?) dBm")
FREQ_RE = re.compile(r"^\s*freq:\s*(\d+)")
SSID_RE = re.compile(r"^\s*SSID:\s*(.*)")

#----Functions----#
def freq_to_channel(freq_mhz: int) -> int | None:
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
    if 2412 <= freq_mhz <= 2472: return (freq_mhz - 2407) // 5
    if freq_mhz == 2484: return 14
    if 5000 <= freq_mhz <= 5900: return (freq_mhz - 5000) // 5
    return None

def parse_block(lines: List) -> dict:
    """
    Parse a block of output from the iwlist command into a dictionary
    containing Wi-Fi network information.

    Args:
        lines: A list of lines from the output of the iwlist command,
            representing a single block of a Wi-Fi network.

    Returns:
        A dictionary containing the parsed Wi-Fi network information.
        The dictionary will contain the following keys:
            - "bssid": The MAC address of the Wi-Fi network.
            - "ssid": The network name of the Wi-Fi network.
            - "signal_dbm": The signal strength of the Wi-Fi network in dBm.
            - "freq_mhz": The frequency of the Wi-Fi network in MHz.
            - "channel": The Wi-Fi channel number of the network, if a mapping exists.
    """
    rec = {"bssid": None, "ssid": None, "signal_dbm": None, "freq_mhz": None, "channel": None}
    for line in lines:
        if m := BSS_RE.match(line):
            rec["bssid"] = m.group(1).lower()
        elif m := SIG_RE.match(line):
            rec["signal_dbm"] = float(m.group(1))
        elif m := FREQ_RE.match(line):
            rec["freq_mhz"] = int(m.group(1))
        elif m := SSID_RE.match(line):
            rec["ssid"] = m.group(1)
    if rec["freq_mhz"]:
        rec["channel"] = freq_to_channel(rec["freq_mhz"])
    return rec

#----Core Async Tasks----
async def run_iw_scan(interface: str, timeout: float=20.0) -> list[dict]:
    """
    Run an iwlist scan to get a list of Wi-Fi networks.

    Args:
        interface: The Wi-Fi interface to use for scanning.

    Returns:
        A list of dictionaries containing the parsed Wi-Fi network information.
        The dictionaries will contain the following keys:
            - "bssid": The MAC address of the Wi-Fi network.
            - "ssid": The network name of the Wi-Fi network.
            - "signal_dbm": The signal strength of the Wi-Fi network in dBm.
            - "freq_mhz": The frequency of the Wi-Fi network in MHz.
            - "channel": The Wi-Fi channel number of the network, if a mapping exists.
    """
    proc = await asyncio.create_subprocess_exec(
        "iw", "dev", interface, "scan", 
        stdout=asyncio.subprocess.PIPE, 
        stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.send_signal(signal.SIGKILL)
        except ProcessLookupError: pass
        raise RuntimeError(f"iwlist scan timed out after {timeout} seconds")
    if proc.returncode != 0:
        raise RuntimeError(f"iwlist scan failed ({proc.returncode}): {err.decode(errors='ignore')}")
    lines = out.decode(errors="ignore").splitlines()
    recs, block = [], []
    for line in lines:
       if BSS_RE.match(line):
           if block: recs.append(parse_block(block))
           block = []
       block.append(line)
    if block: recs.append(parse_block(block))
    print(f"[producer] Found {len(recs)} networks")
    return [r for r in recs if r.get("bssid") and r.get("signal_dbm") is not None]

async def producer(queue: asyncio.Queue, iface: str, 
                   interval: float, ssid_filter: str=None) -> None:
    """
    Producer task that runs an iwlist scan at a given interval and puts
    the results into a queue. The producer can be configured to filter
    the results by a specific SSID.

    Args:
        queue: The queue to put the scan results into.
        iface: The Wi-Fi interface to use for scanning.
        interval: The interval between scans in seconds.
        ssid_filter: The optional SSID to filter the results by.
    """
    backoff = 1.0 #seconds
    while True:
        ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            recs = await run_iw_scan(iface, timeout=20.0)
            if ssid_filter:
                recs = [r for r in recs if r["ssid"] == ssid_filter]
            await queue.put((ts, recs))
            backoff = 1.0
            print(f"[debug] producer queued batch at {ts} | current queue size: {queue.qsize()}")
            await asyncio.sleep(max(0.1, interval))
        except Exception as e:
            print(f"[producer] {e}", file=sys.stderr)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, 30.0)
        await asyncio.sleep(interval)
        

async def consumer(queue: asyncio.Queue, out_path: str, location: str=None) -> None:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    wrote_header = os.path.exists(out_path) and os.path.getsize(out_path) > 0
    with open(out_path, "a", newline="") as f:
        writer = csv.writer(f)
        if not wrote_header:
            writer.writerow(["timestamp-utc", "location", "iface", "bssid", "ssid", "signal_dbm", "freq_mhz", "channel"])
            f.flush()
        while True:
            item = await queue.get()
            try:
                ts, recs = item
                for r in recs:
                    writer.writerow([
                        ts,
                        location,
                        os.environ.get("IFACE", "wlan0"),
                        r.get("bssid"), 
                        r.get("ssid"),
                        r.get("signal_dbm"),
                        r.get("freq_mhz"),
                        r.get("channel")
                    ])
                f.flush()
                print(f"[consumer] wrote {len(recs)} records to {out_path}")
            except Exception as e:
                print(f"[consumer] {e}")
            finally:
                queue.task_done()
            await asyncio.sleep(0.01)
            
#----Main----
async def main():

    """
    Main entry point for the script.

    This function sets up the producer and consumer tasks, and adds signal
    handlers for SIGINT and SIGTERM to stop the tasks.

    The producer task runs the `producer` function, which scans for Wi-Fi
    networks using the `iwlist` command, and sends the results to the consumer
    task using the `queue`.

    The consumer task runs the `consumer` function, which writes the results
    to a CSV file.

    The signal handlers are added to the event loop using
    `loop.add_signal_handler()`. When a signal is received, the `_stop`
    function is called, which sets the `stop` event.

    The `stop` event is used to cancel the producer and consumer tasks.
    """
    parser = argparse.ArgumentParser(description="Asyncronous Wi-Fi RSSI Logger")
    parser.add_argument("--if", dest="iface", default="wlan0", help="Interface to scan (default: wlan0)")
    parser.add_argument("--interval", type=float, default=5.0, help="Scan interval seconds (default: 1)")
    parser.add_argument("--out", default="/data/wifi_rssi_log.csv", help="Output file (default: /data/wifi_rssi_log.csv)")
    parser.add_argument("--ssid", default=None, help="Optional Filter by SSID")
    parser.add_argument("--location", type=str, default=None, help="Optional Location Tag")
    args = parser.parse_args()
    print(f"[main] iface: {args.iface} | interval: {args.interval} | out: {args.out} | location: {args.location} | ssid: {args.ssid}") 
    
    q = asyncio.Queue(maxsize=2)
    prod = asyncio.create_task(producer(q, args.iface, args.interval, args.ssid))
    cons = asyncio.create_task(consumer(q, args.out, args.location))
    
    """
    Set up signal handlers for SIGINT and SIGTERM to stop the producer
    and consumer tasks.

    The signal handlers are added to the event loop using
    `loop.add_signal_handler()`. When a signal is received, the `_stop`
    function is called, which sets the `stop` event.

    The `stop` event is used to cancel the producer and consumer tasks.
    """
    stop = asyncio.Event()
    def _stop(*_): stop.set()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try: loop.add_signal_handler(sig, _stop)
        except NotImplementedError: pass
    await stop.wait()
    prod.cancel(); cons.cancel()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    
        