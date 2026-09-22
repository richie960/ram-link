#!/usr/bin/env python3
"""
RAM-Link sustained borrowed-memory test.

This is deliberately a soak test: it BORROWS one RAM block from the
Android/Termux server, repeatedly writes and reads that same block for
a sustained period, verifies its contents, sends lease keepalives,
then RELEASES the block.
"""

import argparse
import hashlib
import socket
import struct
import time

from ramlink_client import discover_phone

PORT = 18080
MAGIC = b"RML1"
HEADER = struct.Struct("!4sBQI")
LEASE_REPLY = struct.Struct("!QQQ")

OP_BORROW = 8
OP_RELEASE = 9
OP_KEEPALIVE = 10
OP_READ = 2
OP_WRITE = 3
MAX_TRANSFER = 1024 * 1024
SECTOR_SIZE = 512


def recv_all(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(min(MAX_TRANSFER, size - len(data)))
        if not chunk:
            raise ConnectionError("RAM-Link server disconnected")
        data.extend(chunk)
    return bytes(data)


def request(sock, op, offset=0, length=0, payload=b""):
    sock.sendall(HEADER.pack(MAGIC, op, offset, length))
    if payload:
        sock.sendall(payload)

    magic, response_op, response_offset, response_length = HEADER.unpack(
        recv_all(sock, HEADER.size)
    )
    if magic != MAGIC or response_op != op:
        raise ValueError(
            f"Bad response: op={response_op}, offset={response_offset}"
        )

    return response_offset, recv_all(sock, response_length) if response_length else b""


def write_all(sock, base, data):
    position = 0
    while position < len(data):
        size = min(MAX_TRANSFER, len(data) - position)
        request(
            sock,
            OP_WRITE,
            base + position,
            size,
            data[position:position + size],
        )
        position += size


def read_all(sock, base, size):
    result = bytearray()
    position = 0
    while position < size:
        amount = min(MAX_TRANSFER, size - position)
        _, data = request(sock, OP_READ, base + position, amount)
        if len(data) != amount:
            raise ValueError("Short read")
        result.extend(data)
        position += amount
    return bytes(result)


def pattern(size, generation):
    seed = hashlib.sha256(
        f"RAM-LINK generation {generation}".encode()
    ).digest()
    return (seed * ((size // len(seed)) + 1))[:size]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mb", type=int, default=64,
                        help="RAM block to borrow in MiB (default: 64)")
    parser.add_argument("--seconds", type=int, default=120,
                        help="How long to keep using it (default: 120)")
    parser.add_argument("--interval", type=int, default=10,
                        help="Seconds between lease keepalives (default: 10)")
    args = parser.parse_args()

    if args.mb < 1:
        raise SystemExit("--mb must be >= 1")
    if args.seconds < 1:
        raise SystemExit("--seconds must be >= 1")

    host = discover_phone()
    if not host:
        host = input("Enter phone IP manually: ").strip()
    if not host:
        raise SystemExit("No phone selected")

    sock = socket.socket()
    sock.settimeout(30)
    sock.connect((host, PORT))

    lease_id = None

    try:
        print(f"Connected: {host}:{PORT}")
        _, reply = request(sock, OP_BORROW, length=args.mb * 1024 * 1024)
        lease_id, base, length = LEASE_REPLY.unpack(reply)

        print(f"BORROWED lease={lease_id}")
        print(f"RAM offset={base:,}")
        print(f"RAM size={length / 1024 / 1024:.1f} MiB")
        print("The same memory block will now be actively used.")

        generation = 0
        started = time.monotonic()
        last_keepalive = started
        operations = 0
        failures = 0

        while time.monotonic() - started < args.seconds:
            generation += 1
            data = pattern(length, generation)

            write_all(sock, base, data)
            returned = read_all(sock, base, length)
            operations += 1

            expected_hash = hashlib.sha256(data).digest()
            actual_hash = hashlib.sha256(returned).digest()

            if actual_hash != expected_hash:
                failures += 1
                raise RuntimeError(
                    f"DATA CORRUPTION at generation {generation}"
                )

            now = time.monotonic()
            if now - last_keepalive >= args.interval:
                request(sock, OP_KEEPALIVE, lease_id)
                last_keepalive = now

            elapsed = now - started
            print(
                f"lease={lease_id}  "
                f"used={elapsed:6.1f}s  "
                f"cycles={operations}  "
                f"verify=PASS"
            )

        print("\nSUSTAINED BORROW TEST: PASS")
        print(f"Cycles: {operations}")
        print(f"Failures: {failures}")
        print(f"Held for: {time.monotonic() - started:.1f}s")

    finally:
        if lease_id is not None:
            try:
                request(sock, OP_RELEASE, lease_id)
                print(f"RELEASED lease={lease_id}")
            except Exception as exc:
                print(f"WARNING: release failed: {exc}")
        sock.close()


if __name__ == "__main__":
    main()
