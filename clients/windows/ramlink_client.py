#!/usr/bin/env python3
import hashlib
import ipaddress
import re
import socket
import struct
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

PORT = 8081
MAGIC = b"RML1"
HEADER = struct.Struct("!4sBQI")
OP_INFO, OP_READ, OP_WRITE, OP_PING = 1, 2, 3, 4
MAX_BLOCK = 1024 * 1024
DISCOVERY_TIMEOUT = 0.20
DISCOVERY_WORKERS = 64
DISCOVERY_MAX_HOSTS = 1024


def recv_all(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(min(MAX_BLOCK, size - len(data)))
        if not chunk:
            raise ConnectionError("Server disconnected")
        data.extend(chunk)
    return bytes(data)


def ping_host(host, timeout=DISCOVERY_TIMEOUT):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((host, PORT))
        s.sendall(HEADER.pack(MAGIC, OP_PING, 0, 0))
        header = recv_all(s, HEADER.size)
        magic, op, _, length = HEADER.unpack(header)
        if magic != MAGIC or op != OP_PING or length != 4:
            return None
        if recv_all(s, length) == b"PONG":
            return host
    except (OSError, ConnectionError, ValueError):
        pass
    finally:
        s.close()
    return None


def local_networks():
    """Find small private IPv4 networks on Windows using only stdlib tools."""
    try:
        output = subprocess.check_output(
            ["ipconfig"], text=True, encoding="mbcs", errors="replace"
        )
    except (OSError, subprocess.SubprocessError):
        return []

    ipv4_re = re.compile(r"IPv4[^:]*:\s*([0-9.]+)", re.IGNORECASE)
    mask_re = re.compile(r"Subnet Mask[^:]*:\s*([0-9.]+)", re.IGNORECASE)

    # Parse each adapter block independently so an IPv4 address is paired
    # with the subnet mask belonging to the same adapter.
    blocks = re.split(r"\r?\n\s*\r?\n", output)
    networks = []

    for block in blocks:
        ip_match = ipv4_re.search(block)
        mask_match = mask_re.search(block)
        if not ip_match or not mask_match:
            continue

        try:
            addr = ipaddress.IPv4Address(ip_match.group(1))
            network = ipaddress.IPv4Network(
                f"{addr}/{mask_match.group(1)}", strict=False
            )
            if addr.is_loopback or addr.is_link_local or not addr.is_private:
                continue
            if network.num_addresses > DISCOVERY_MAX_HOSTS:
                continue
            networks.append(network)
        except ValueError:
            continue

    return list(dict.fromkeys(networks))


def discover_phone():
    """Discover the Android RAM-Link server without asking for its IP."""
    print("Searching local IPv4 networks for RAM-Link on TCP port", PORT)
    networks = local_networks()

    if not networks:
        print("No small private IPv4 network was found.")
        return None

    candidates = []
    for network in networks:
        print("  Scanning", network)
        candidates.extend(str(ip) for ip in network.hosts())

    with ThreadPoolExecutor(max_workers=DISCOVERY_WORKERS) as pool:
        futures = [pool.submit(ping_host, host) for host in candidates]
        for future in as_completed(futures):
            host = future.result()
            if host:
                print("RAM-Link phone found at:", host)
                return host

    print("RAM-Link phone was not found automatically.")
    print("Check that USB tethering is enabled and server.py is running.")
    return None


def request(sock, op, offset=0, length=0, data=b""):
    if op == OP_WRITE and length != len(data):
        raise ValueError("WRITE length must equal payload length")

    sock.sendall(HEADER.pack(MAGIC, op, offset, length))
    if data:
        sock.sendall(data)

    magic, rop, roff, rlen = HEADER.unpack(recv_all(sock, HEADER.size))
    if magic != MAGIC:
        raise ValueError("Invalid response")
    if op == OP_READ and rlen != length:
        raise ValueError(f"Read length mismatch: expected {length}, got {rlen}")

    return rop, roff, recv_all(sock, rlen) if rlen else b""


def connect_to_phone():
    host = discover_phone()

    # Manual fallback keeps the client usable on unusual tethering setups.
    if not host:
        manual = input("Enter phone IP manually (or press Enter to exit): ").strip()
        if not manual:
            return None
        host = manual

    s = socket.socket()
    s.settimeout(15)

    try:
        s.connect((host, PORT))
        print("Connected to RAM-Link:", host)
        return s
    except OSError as e:
        print("CONNECTION FAILED:", e)
        s.close()
        return None


def main():
    s = connect_to_phone()
    if s is None:
        return

    try:
        while True:
            print(
                "\n1 INFO\n2 PING\n3 WRITE\n4 READ\n"
                "5 INTEGRITY\n6 REDISCOVER PHONE\n7 EXIT"
            )
            c = input("Select: ").strip()

            if c == "1":
                print(request(s, OP_INFO)[2].decode(errors="replace"))

            elif c == "2":
                t = time.perf_counter()
                print(
                    "PING:",
                    request(s, OP_PING)[2].decode(),
                    "%.3f ms" % ((time.perf_counter() - t) * 1000),
                )

            elif c in ("3", "4", "5"):
                mb = int(input("MB [1]: ").strip() or "1")
                size = mb * 1024 * 1024
                pattern = (bytes(range(256)) * ((size // 256) + 1))[:size]

                if c in ("3", "5"):
                    for offset in range(0, size, MAX_BLOCK):
                        length = min(MAX_BLOCK, size - offset)
                        request(
                            s, OP_WRITE, offset, length,
                            pattern[offset:offset + length]
                        )

                if c in ("4", "5"):
                    out = bytearray()
                    for offset in range(0, size, MAX_BLOCK):
                        length = min(MAX_BLOCK, size - offset)
                        out.extend(request(s, OP_READ, offset, length)[2])

                    if c == "5":
                        print(
                            "INTEGRITY:",
                            "PASS"
                            if hashlib.sha256(out).digest()
                            == hashlib.sha256(pattern).digest()
                            else "FAIL",
                        )

            elif c == "6":
                s.close()
                s = connect_to_phone()
                if s is None:
                    return

            elif c == "7":
                break
    finally:
        s.close()


if __name__ == "__main__":
    main()
