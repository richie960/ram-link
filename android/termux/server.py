#!/usr/bin/env python3
"""
RAM-Link Termux server.

The phone owns one volatile RAM buffer. Clients can borrow a reserved
RAM block with BORROW, keep it alive, use it, and RELEASE it.
"""

import socket
import struct
import sys
import threading
import time

HOST = "0.0.0.0"
PORT = 18080
MAGIC = b"RML1"

# 17-byte wire header: magic, operation, offset/lease-id, length.
HEADER = struct.Struct("!4sBQI")
LEASE_REPLY = struct.Struct("!QQQ")  # lease_id, byte_offset, byte_length

OP_INFO = 1
OP_READ = 2
OP_WRITE = 3
OP_PING = 4
OP_BLOCK_INFO = 5
OP_BLOCK_READ = 6
OP_BLOCK_WRITE = 7
OP_BORROW = 8
OP_RELEASE = 9
OP_KEEPALIVE = 10

SECTOR_SIZE = 512
MAX_BLOCK = 1024 * 1024
LEASE_SECONDS = 120


class Lease:
    def __init__(self, lease_id, offset, length):
        self.lease_id = lease_id
        self.offset = offset
        self.length = length
        self.expires_at = time.monotonic() + LEASE_SECONDS
        self.lock = threading.Lock()

    def alive(self):
        return time.monotonic() < self.expires_at

    def keepalive(self):
        with self.lock:
            self.expires_at = time.monotonic() + LEASE_SECONDS


class RAMLinkServer:
    def __init__(self, size_mb):
        self.size = (size_mb * 1024 * 1024 // SECTOR_SIZE) * SECTOR_SIZE
        if self.size < SECTOR_SIZE:
            raise ValueError("RAM size must be at least 1 sector")

        try:
            self.memory = bytearray(self.size)
        except MemoryError:
            raise SystemExit("ERROR: Not enough Android RAM.")

        self.sectors = self.size // SECTOR_SIZE
        self.memory_lock = threading.RLock()
        self.leases = {}
        self.lease_lock = threading.RLock()
        self.next_lease_id = 1

        print("RAM-LINK TERMUX SERVER")
        print(f"RAM buffer: {self.size:,} bytes ({self.size / 1024 / 1024:.1f} MiB)")
        print(f"Sectors: {self.sectors:,}")
        print(f"TCP: {HOST}:{PORT}")
        print(f"Lease duration: {LEASE_SECONDS}s")

    @staticmethod
    def recv_all(conn, size):
        data = bytearray()
        while len(data) < size:
            chunk = conn.recv(min(MAX_BLOCK, size - len(data)))
            if not chunk:
                raise ConnectionError("peer disconnected")
            data.extend(chunk)
        return bytes(data)

    @staticmethod
    def send_header(conn, op, offset, length):
        conn.sendall(HEADER.pack(MAGIC, op, offset, length))

    def valid_range(self, offset, length):
        return (
            offset >= 0
            and length >= 0
            and offset <= self.size
            and length <= self.size - offset
        )

    def find_free_region(self, length):
        with self.lease_lock:
            leases = sorted(
                (x for x in self.leases.values() if x.alive()),
                key=lambda x: x.offset,
            )

            cursor = 0
            for lease in leases:
                if cursor + length <= lease.offset:
                    return cursor
                cursor = max(cursor, lease.offset + lease.length)

            if cursor + length <= self.size:
                return cursor

        return None

    def cleanup_expired(self):
        with self.lease_lock:
            expired = [
                lease_id
                for lease_id, lease in self.leases.items()
                if not lease.alive()
            ]
            for lease_id in expired:
                del self.leases[lease_id]

    def borrow(self, conn, requested_length):
        self.cleanup_expired()

        length = (
            (requested_length + SECTOR_SIZE - 1) // SECTOR_SIZE
        ) * SECTOR_SIZE

        if length <= 0 or length > self.size:
            raise ValueError("Invalid borrow size")

        offset = self.find_free_region(length)
        if offset is None:
            raise RuntimeError("No free RAM block is currently available")

        with self.lease_lock:
            lease_id = self.next_lease_id
            self.next_lease_id += 1
            lease = Lease(lease_id, offset, length)
            self.leases[lease_id] = lease

        # Zero the borrowed block so every lease starts from known data.
        with self.memory_lock:
            self.memory[offset:offset + length] = b"\x00" * length

        payload = LEASE_REPLY.pack(lease_id, offset, length)
        self.send_header(conn, OP_BORROW, lease_id, len(payload))
        conn.sendall(payload)

        print(
            f"[BORROW] id={lease_id} offset={offset} "
            f"size={length / 1024 / 1024:.1f} MiB"
        )

    def get_lease(self, lease_id):
        with self.lease_lock:
            lease = self.leases.get(lease_id)
            if lease is None or not lease.alive():
                if lease is not None:
                    del self.leases[lease_id]
                raise ValueError("Lease is missing or expired")
            return lease

    def release(self, lease_id):
        with self.lease_lock:
            lease = self.leases.pop(lease_id, None)
        if lease is None:
            raise ValueError("Unknown lease")

        print(f"[RELEASE] id={lease_id}")
        self.send_header(current_conn[0], OP_RELEASE, lease_id, 0)

    def info(self, conn):
        self.cleanup_expired()
        with self.lease_lock:
            active = len(self.leases)

        text = (
            "RAM-LINK\n"
            "version=3\n"
            "protocol=RML1\n"
            "transport=USB_TETHERING\n"
            f"buffer_bytes={self.size}\n"
            f"buffer_mib={self.size / 1024 / 1024:.2f}\n"
            f"sector_size={SECTOR_SIZE}\n"
            f"sector_count={self.sectors}\n"
            f"max_transfer={MAX_BLOCK}\n"
            f"active_leases={active}\n"
            f"lease_seconds={LEASE_SECONDS}\n"
        ).encode()

        self.send_header(conn, OP_INFO, 0, len(text))
        conn.sendall(text)

    def handle(self, conn, op, offset, length):
        if op == OP_INFO:
            self.info(conn)
            return

        if op == OP_PING:
            self.send_header(conn, OP_PING, 0, 4)
            conn.sendall(b"PONG")
            return

        if op == OP_BORROW:
            self.borrow(conn, length)
            return

        if op == OP_RELEASE:
            self.get_lease(offset)
            with self.lease_lock:
                self.leases.pop(offset, None)
            print(f"[RELEASE] id={offset}")
            self.send_header(conn, OP_RELEASE, offset, 0)
            return

        if op == OP_KEEPALIVE:
            lease = self.get_lease(offset)
            lease.keepalive()
            self.send_header(conn, OP_KEEPALIVE, offset, 0)
            return

        if op in (OP_READ, OP_WRITE):
            if length > MAX_BLOCK or not self.valid_range(offset, length):
                raise ValueError("Invalid byte range")

            if op == OP_WRITE:
                data = self.recv_all(conn, length)
                with self.memory_lock:
                    self.memory[offset:offset + length] = data
                self.send_header(conn, OP_WRITE, offset, length)
            else:
                with self.memory_lock:
                    data = bytes(self.memory[offset:offset + length])
                self.send_header(conn, OP_READ, offset, length)
                conn.sendall(data)
            return

        if op == OP_BLOCK_INFO:
            payload = struct.pack("!QQ", SECTOR_SIZE, self.sectors)
            self.send_header(conn, OP_BLOCK_INFO, 0, len(payload))
            conn.sendall(payload)
            return

        if op in (OP_BLOCK_READ, OP_BLOCK_WRITE):
            if offset < 0 or length < 0:
                raise ValueError("Invalid sector range")
            if offset > self.sectors or length > self.sectors - offset:
                raise ValueError("Sector range outside RAM")
            byte_length = length * SECTOR_SIZE
            if byte_length > MAX_BLOCK:
                raise ValueError("Transfer exceeds maximum")

            byte_offset = offset * SECTOR_SIZE

            if op == OP_BLOCK_WRITE:
                data = self.recv_all(conn, byte_length)
                with self.memory_lock:
                    self.memory[byte_offset:byte_offset + byte_length] = data
                self.send_header(conn, OP_BLOCK_WRITE, offset, length)
            else:
                with self.memory_lock:
                    data = bytes(
                        self.memory[byte_offset:byte_offset + byte_length]
                    )
                self.send_header(conn, OP_BLOCK_READ, offset, length)
                conn.sendall(data)
            return

        raise ValueError(f"Unknown operation {op}")

    def client(self, conn, address):
        print(f"[+] Connected: {address}")
        try:
            while True:
                header = self.recv_all(conn, HEADER.size)
                magic, op, offset, length = HEADER.unpack(header)
                if magic != MAGIC:
                    raise ValueError("Invalid protocol magic")
                self.handle(conn, op, offset, length)
        except Exception as exc:
            print(f"[-] {address}: {exc}")
        finally:
            conn.close()

    def start(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(8)
        print("\nSERVER READY")
        print(f"Connect to the phone on TCP {PORT}.")
        print("Press Ctrl+C to stop.\n")

        try:
            while True:
                conn, address = server.accept()
                threading.Thread(
                    target=self.client,
                    args=(conn, address),
                    daemon=True,
                ).start()
        except KeyboardInterrupt:
            print("\nStopping RAM-Link.")
        finally:
            server.close()


if __name__ == "__main__":
    mb = int(sys.argv[1]) if len(sys.argv) > 1 else 512
    if mb < 1:
        raise SystemExit("Usage: python server.py <RAM_MB>")
    RAMLinkServer(mb).start()
