#!/usr/bin/env python3
import asyncio
import csv
import os
import re
import signal
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

# ---------- argparse ----------
import argparse

def parse_args():
    p = argparse.ArgumentParser(description="Async Wi-Fi RSSI scanner with target-aware fast scans")
    p.add_argument("--if", dest="iface", default="wlan0", help="Wireless interface (default: wlan0)")
    p.add_argument("--interval", type=float, default=4.0, help="Scan interval seconds (default: 4.0)")
    p.add_argument("--timeout", type=float, default=3.5, help="Per-scan timeout seconds (default: 3.5)")
    p.add_argument("--out", default="/data/wifi_rssi_log.csv", help="CSV output path (default: /data/wifi_rssi_log.csv)")
    p.add_argument("--targets", type=str, help="Comma-separated SSIDs or BSSIDs to prioritize (e.g. 'HomeWiFi,Office-AP')")
    p.add_argument("--full-scan-mins", type=float, default=10.0, help="Full discovery cadence in minutes (default: 10)")
    p.add_argument("--flush-every", type=int, default=5, help="Flush CSV every N batches (default: 5)")
    return p.parse_args()

# ---------- helpers: iw parsing ----------

BSS_RE      = re.compile(r"^BSS\s+([0-9a-fA-F:]{17})\b")
FREQ_RE     = re.compile(r"^\s*freq:\s*(\d+)")
SIGNAL_RE   = re.compile(r"^\s*signal:\s*([+-]?\d+(?:\.\d+)?)\s*dBm")
SSID_RE     = re.compile(r"^\s*SSID:\s*(.*)$")

def freq_to_channel(freq_mhz: int) -> Optional[int]:
    # 2.4 GHz: 2412 + 5*(ch-1), channels 1..14
    if 2400 <= freq_mhz < 2500:
        ch = int(round((freq_mhz - 2412) / 5)) + 1
        return ch if 1 <= ch <= 14 else None
    # 5 GHz common mapping: 5000 + 5*ch
    if 4900 <= freq_mhz <= 5900:
        ch = int(round((freq_mhz - 5000) / 5))
        return ch if 0 < ch < 200 else None
    return None

def parse_iw_output(lines: List[str]) -> List[Dict[str, Any]]:
    """Parse `iw ... scan` plaintext into a list of records."""
    recs = []
    cur: Dict[str, Any] = {}
    for line in lines:
        line = line.rstrip("\n")
        m = BSS_RE.match(line)
        if m:
            if cur:
                recs.append(cur)
            cur = {"bssid": m.group(1).lower()}
            continue
        m = FREQ_RE.match(line)
        if m and cur is not None:
            cur["freq_mhz"] = int(m.group(1))
            cur["channel"] = freq_to_channel(cur["freq_mhz"])
            continue
        m = SIGNAL_RE.match(line)
        if m and cur is not None:
            try:
                cur["signal_dbm"] = float(m.group(1))
            except ValueError:
                pass
            continue
        m = SSID_RE.match(line)
        if m and cur is not None:
            ssid = (m.group(1) or "").strip()
            cur["ssid"] = ssid if ssid else None
            continue
    if cur:
        recs.append(cur)
    return recs

# ---------- subprocess: run iw ----------

async def run_and_decode(cmd: List[str], timeout: float) -> List[str]:
    print("[scan]", " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        with contextlib_silent():
            proc.kill()
            await proc.wait()
        raise RuntimeError(f"scan timeout after {timeout:.1f}s")
    if proc.returncode != 0:
        raise RuntimeError(f"iw failed ({proc.returncode}): {err.decode(errors='ignore')}")
    return out.decode(errors="ignore").splitlines()

async def run_iw_scan_all(iface: str, timeout: float) -> List[str]:
    # Full discovery (APs only)
    return await run_and_decode(["iw","dev",iface,"scan","ap-force"], timeout)

async def run_iw_scan_freqs(iface: str, freqs_mhz: List[int], timeout: float) -> List[str]:
    # Narrow scan: only the frequencies we care about
    freqlist = [str(f) for f in freqs_mhz]
    return await run_and_decode(["iw","dev",iface,"scan","ap-force","freq", *freqlist], timeout)

# ---------- contextlib helper ----------
from contextlib import contextmanager
@contextmanager
def contextlib_silent():
    try:
        yield
    except Exception:
        pass

# ---------- CSV consumer with batching ----------

async def consumer(queue: asyncio.Queue, out_path: str, flush_every: int):
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    header = ["timestamp_utc","iface","bssid","ssid","signal_dbm","freq_mhz","channel"]

    # Large user-space buffer helps on SD cards
    wrote_header = os.path.exists(out_path) and os.path.getsize(out_path) > 0
    pending = 0
    with open(out_path, "a", newline="", buffering=1_048_576) as f:
        w = csv.writer(f)
        if not wrote_header:
            w.writerow(header)
            f.flush()

        while True:
            ts, iface, recs = await queue.get()
            try:
                if recs:
                    rows = [
                        [ts, iface, r.get("bssid"), r.get("ssid"),
                         r.get("signal_dbm"), r.get("freq_mhz"), r.get("channel")]
                        for r in recs
                    ]
                    w.writerows(rows)
                    pending += 1
                    if pending >= flush_every:
                        f.flush()
                        pending = 0
            finally:
                queue.task_done()

# ---------- target-aware producer ----------

async def producer(queue: asyncio.Queue,
                   iface: str,
                   interval: float,
                   timeout: float,
                   targets: set[str],
                   full_scan_every: timedelta):

    # caches
    bssid_to_freq: Dict[str,int] = {}
    ssid_to_freqs: Dict[str,set[int]] = defaultdict(set)
    last_full = datetime.min

    loop = asyncio.get_running_loop()
    backoff = 1.0

    def want_record(r: Dict[str,Any]) -> bool:
        if not targets:
            return True
        ssid = (r.get("ssid") or "").strip()
        bssid = (r.get("bssid") or "").lower()
        return (ssid in targets) or (bssid in targets)

    async def full_discovery() -> List[Dict[str,Any]]:
        nonlocal last_full, bssid_to_freq, ssid_to_freqs
        lines = await run_iw_scan_all(iface, timeout=max(timeout, 4.5))
        recs = parse_iw_output(lines)
        # rebuild caches
        bssid_to_freq = {}
        ssid_to_freqs = defaultdict(set)
        for r in recs:
            b, s, f = r.get("bssid"), (r.get("ssid") or "").strip(), r.get("freq_mhz")
            if b and f:
                bssid_to_freq[b] = f
            if s and f:
                ssid_to_freqs[s].add(f)
        last_full = datetime.utcnow()
        return recs

    async def fast_scan_on_targets() -> List[Dict[str,Any]]:
        # Build unique frequency set for targets
        freqs: set[int] = set()
        for t in targets:
            # match by SSID cache
            freqs |= ssid_to_freqs.get(t, set())
            # match by BSSID cache
            if t.lower() in bssid_to_freq:
                freqs.add(bssid_to_freq[t.lower()])
        # If no cache yet -> full discovery
        if not freqs:
            return await full_discovery()
        # Narrow scan
        lines = await run_iw_scan_freqs(iface, sorted(freqs), timeout=timeout)
        recs = parse_iw_output(lines)
        # If none of the targets are visible, do a one-off full discovery
        if targets and not any(want_record(r) for r in recs):
            return await full_discovery()
        # Opportunistically refresh caches
        for r in recs:
            b, s, f = r.get("bssid"), (r.get("ssid") or "").strip(), r.get("freq_mhz")
            if b and f:
                bssid_to_freq[b.lower()] = f
            if s and f:
                ssid_to_freqs[s].add(f)
        return recs

    # main loop at fixed cadence (no overlap)
    next_t = loop.time()
    while True:
        next_t += interval
        ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            # periodic full discovery
            if (datetime.utcnow() - last_full) > full_scan_every:
                recs = await full_discovery()
            else:
                recs = await fast_scan_on_targets()

            # post-filter records to targets if provided
            if targets:
                recs = [r for r in recs if want_record(r)]

            await queue.put((ts, iface, recs))
            backoff = 1.0
        except Exception as e:
            print(f"[producer] {e}; backoff={backoff:.1f}s", file=sys.stderr)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

        # sleep the remaining time to the next slot
        delay = max(0.05, next_t - loop.time())
        await asyncio.sleep(delay)

# ---------- main ----------

async def main():
    args = parse_args()

    # Build target set (SSIDs or BSSIDs) from --targets
    targets: set[str] = set()
    if args.targets:
        targets = {t.strip() for t in args.targets.split(",") if t.strip()}

    print(f"[config] iface={args.iface} interval={args.interval}s timeout={args.timeout}s out={args.out}")
    print(f"[config] targets={sorted(targets) if targets else 'None (log all)'}")

    q: asyncio.Queue = asyncio.Queue(maxsize=2)
    prod = asyncio.create_task(
        producer(q, args.iface, args.interval, args.timeout, targets, timedelta(minutes=args.full_scan_mins))
    )
    cons = asyncio.create_task(consumer(q, args.out, args.flush_every))

    # Graceful shutdown on SIGINT/SIGTERM
    stop = asyncio.Event()
    def _stop():
        stop.set()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    await stop.wait()
    print("[main] stopping…")
    prod.cancel()
    try:
        await prod
    except asyncio.CancelledError:
        pass
    # drain queue
    await q.join()
    cons.cancel()
    try:
        await cons
    except asyncio.CancelledError:
        pass
    print("[main] done")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass






# import asyncio, os, re, csv, sys, signal, argparse
# from datetime import datetime
# #import pandas as pd
# from typing import Dict, List

# #----Regular Expressions----#
# """
# Regular expressions used to parse output of iwlist command.

# BSS_RE: Matches BSS lines containing MAC addresses.
# SIG_RE: Matches signal strength lines containing dBm values.
# FREQ_RE: Matches frequency lines containing MHz values.
# SSID_RE: Matches SSID lines containing network names.
# """
# BSS_RE = re.compile(r"^BSS ([0-9a-f:]{17})")
# SIG_RE = re.compile(r"^\s*signal:\s*(-?\d+(?:\.\d+)?) dBm")
# FREQ_RE = re.compile(r"^\s*freq:\s*(\d+)")
# SSID_RE = re.compile(r"^\s*SSID:\s*(.*)")

# #----Functions----#
# def freq_to_channel(freq_mhz: int) -> int | None:
#     """
#     Convert a frequency in MHz to a Wi-Fi channel number.

#     This function uses the following channel to frequency mappings:
#     - 2.4 GHz band: channels 1-14, frequencies 2412-2472 MHz
#     - 5 GHz band: channels 36-180, frequencies 5000-5900 MHz
#     - Channel 14: frequency 2484 MHz

#     Args:
#         freq_mhz: The frequency in MHz to convert.

#     Returns:
#         The corresponding Wi-Fi channel number, or None if no mapping exists.
#     """
#     if 2412 <= freq_mhz <= 2472: return (freq_mhz - 2407) // 5
#     if freq_mhz == 2484: return 14
#     if 5000 <= freq_mhz <= 5900: return (freq_mhz - 5000) // 5
#     return None

# def parse_block(lines: List) -> dict:
#     """
#     Parse a block of output from the iwlist command into a dictionary
#     containing Wi-Fi network information.

#     Args:
#         lines: A list of lines from the output of the iwlist command,
#             representing a single block of a Wi-Fi network.

#     Returns:
#         A dictionary containing the parsed Wi-Fi network information.
#         The dictionary will contain the following keys:
#             - "bssid": The MAC address of the Wi-Fi network.
#             - "ssid": The network name of the Wi-Fi network.
#             - "signal_dbm": The signal strength of the Wi-Fi network in dBm.
#             - "freq_mhz": The frequency of the Wi-Fi network in MHz.
#             - "channel": The Wi-Fi channel number of the network, if a mapping exists.
#     """
#     rec = {"bssid": None, "ssid": None, "signal_dbm": None, "freq_mhz": None, "channel": None}
#     for line in lines:
#         if m := BSS_RE.match(line):
#             rec["bssid"] = m.group(1).lower()
#         elif m := SIG_RE.match(line):
#             rec["signal_dbm"] = float(m.group(1))
#         elif m := FREQ_RE.match(line):
#             rec["freq_mhz"] = int(m.group(1))
#         elif m := SSID_RE.match(line):
#             rec["ssid"] = m.group(1)
#     if rec["freq_mhz"]:
#         rec["channel"] = freq_to_channel(rec["freq_mhz"])
#     return rec

# #----Core Async Tasks----
# async def run_iw_scan(interface: str, timeout: float=4.0) -> list[dict]:
#     """
#     Run an iwlist scan to get a list of Wi-Fi networks.

#     Args:
#         interface: The Wi-Fi interface to use for scanning.

#     Returns:
#         A list of dictionaries containing the parsed Wi-Fi network information.
#         The dictionaries will contain the following keys:
#             - "bssid": The MAC address of the Wi-Fi network.
#             - "ssid": The network name of the Wi-Fi network.
#             - "signal_dbm": The signal strength of the Wi-Fi network in dBm.
#             - "freq_mhz": The frequency of the Wi-Fi network in MHz.
#             - "channel": The Wi-Fi channel number of the network, if a mapping exists.
#     """
#     proc = await asyncio.create_subprocess_exec(
#         "iw", "dev", interface, "scan",
#         stdout=asyncio.subprocess.PIPE, 
#         stderr=asyncio.subprocess.PIPE
#     ) #Only scans in the 2.4 GHz band "iw", "dev", interface, "scan",
#     ##"freq", "2412", "2437", "2462", "2484",
#     try:
#         out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
#     except asyncio.TimeoutError:
#         try:
#             proc.send_signal(signal.SIGKILL)
#         except ProcessLookupError: pass
#         raise RuntimeError(f"iwlist scan timed out after {timeout} seconds")
#     if proc.returncode != 0:
#         raise RuntimeError(f"iwlist scan failed ({proc.returncode}): {err.decode(errors='ignore')}")
#     lines = out.decode(errors="ignore").splitlines()
#     recs, block = [], []
#     for line in lines:
#        if BSS_RE.match(line):
#            if block: recs.append(parse_block(block))
#            block = []
#        block.append(line)
#     if block: recs.append(parse_block(block))
#     print(f"[producer] Found {len(recs)} networks")
#     return [r for r in recs if r.get("bssid") and r.get("signal_dbm") is not None]

# async def producer(queue: asyncio.Queue, iface: str, 
#                    interval: float, ssid_filter: str=None) -> None:
#     """
#     Producer task that runs an iwlist scan at a given interval and puts
#     the results into a queue. The producer can be configured to filter
#     the results by a specific SSID.

#     Args:
#         queue: The queue to put the scan results into.
#         iface: The Wi-Fi interface to use for scanning.
#         interval: The interval between scans in seconds.
#         ssid_filter: The optional SSID to filter the results by.
#     """
#     backoff = 1.0 #seconds
#     while True:
#         ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
#         try:
#             recs = await run_iw_scan(iface, timeout=4.0)
#             if ssid_filter:
#                 recs = [r for r in recs if r["ssid"] == ssid_filter]
#             await queue.put((ts, recs))
#             backoff = 1.0
#             print(f"[debug] producer queued batch at {ts} | current queue size: {queue.qsize()}")
#             await asyncio.sleep(max(0.1, interval))
#         except Exception as e:
#             print(f"[producer] {e}", file=sys.stderr)
#             await asyncio.sleep(backoff)
#             backoff = min(backoff * 2.0, 30.0)
#         await asyncio.sleep(interval)
        

# async def consumer(queue: asyncio.Queue, out_path: str, location: str=None, 
#                    flush_every: int=5, buffer_bytes: int=1_048_576) -> None:
#     os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
#     wrote_header = os.path.exists(out_path) and os.path.getsize(out_path) > 0
#     pending = 0
#     pending_rows = 0
#     with open(out_path, "a", newline="", buffering=buffer_bytes) as f:
#         writer = csv.writer(f)
#         if not wrote_header:
#             writer.writerow(["timestamp-utc", "location", "iface", "bssid", "ssid", "signal_dbm", "freq_mhz", "channel"])
#             f.flush()
#         while True:
#             item = await queue.get()
#             try:
#                 ts, recs = item
#                 for r in recs:
#                     writer.writerow([
#                         ts,
#                         location,
#                         os.environ.get("IFACE", "wlan0"),
#                         r.get("bssid"), 
#                         r.get("ssid"),
#                         r.get("signal_dbm"),
#                         r.get("freq_mhz"),
#                         r.get("channel")
#                     ])
#                 pending += 1
#                 pending_rows += len(recs)
#                 if pending >= flush_every:
#                     f.flush()
#                     print(f"[consumer] wrote {pending_rows} rows to {out_path}")
#                     pending = 0
#                     pending_rows = 0
#                 print(f"[consumer] queued {len(recs)} records in buffer, pending write to {out_path}")
#             except Exception as e:
#                 print(f"[consumer] {e}")
#             finally:
#                 queue.task_done()
#                 await asyncio.sleep(0.01)
#             await asyncio.sleep(0.01)
            
# #----Main----
# async def main():

#     """
#     Main entry point for the script.

#     This function sets up the producer and consumer tasks, and adds signal
#     handlers for SIGINT and SIGTERM to stop the tasks.

#     The producer task runs the `producer` function, which scans for Wi-Fi
#     networks using the `iwlist` command, and sends the results to the consumer
#     task using the `queue`.

#     The consumer task runs the `consumer` function, which writes the results
#     to a CSV file.

#     The signal handlers are added to the event loop using
#     `loop.add_signal_handler()`. When a signal is received, the `_stop`
#     function is called, which sets the `stop` event.

#     The `stop` event is used to cancel the producer and consumer tasks.
#     """
#     parser = argparse.ArgumentParser(description="Asyncronous Wi-Fi RSSI Logger")
#     parser.add_argument("--if", dest="iface", default="wlan0", help="Interface to scan (default: wlan0)")
#     parser.add_argument("--interval", type=float, default=5.0, help="Scan interval seconds (default: 1)")
#     parser.add_argument("--out", default="/data/wifi_rssi_log.csv", help="Output file (default: /data/wifi_rssi_log.csv)")
#     parser.add_argument("--ssid", default=None, help="Optional Filter by SSID")
#     parser.add_argument("--location", default=None, type=str, help="Optional Location Tag")
#     args = parser.parse_args()
#     print(f"[main] iface: {args.iface} | interval: {args.interval} | out: {args.out} | location: {args.location} | ssid: {args.ssid}") 
    
#     q = asyncio.Queue(maxsize=2)
#     prod = asyncio.create_task(producer(q, args.iface, args.interval, args.ssid))
#     cons = asyncio.create_task(consumer(q, args.out, args.location))
    
#     """
#     Set up signal handlers for SIGINT and SIGTERM to stop the producer
#     and consumer tasks.

#     The signal handlers are added to the event loop using
#     `loop.add_signal_handler()`. When a signal is received, the `_stop`
#     function is called, which sets the `stop` event.

#     The `stop` event is used to cancel the producer and consumer tasks.
#     """
#     stop = asyncio.Event()
#     def _stop(*_): stop.set()
#     loop = asyncio.get_running_loop()
#     for sig in (signal.SIGINT, signal.SIGTERM):
#         try: loop.add_signal_handler(sig, _stop)
#         except NotImplementedError: pass
#     await stop.wait()
#     prod.cancel(); cons.cancel()

# if __name__ == "__main__":
#     try:
#         asyncio.run(main())
#     except KeyboardInterrupt:
#         pass
    
        