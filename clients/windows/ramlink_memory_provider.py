#!/usr/bin/env python3
"""RAM-Link Windows RAM provider."""
import socket, struct, sys, threading, time

HOST = "0.0.0.0"
PORT = 18080
MAGIC = b"RML1"
HEADER = struct.Struct("!4sBQI")
LEASE_REPLY = struct.Struct("!QQQ")
OP_INFO, OP_READ, OP_WRITE, OP_PING = 1, 2, 3, 4
OP_BORROW, OP_RELEASE, OP_KEEPALIVE = 8, 9, 10
SECTOR_SIZE = 512
MAX_BLOCK = 1024 * 1024
LEASE_SECONDS = 120

class Lease:
    def __init__(self, lease_id, offset, length):
        self.lease_id, self.offset, self.length = lease_id, offset, length
        self.expires_at = time.monotonic() + LEASE_SECONDS
        self.lock = threading.Lock()
    def alive(self): return time.monotonic() < self.expires_at
    def keepalive(self):
        with self.lock: self.expires_at = time.monotonic() + LEASE_SECONDS

class RAMProvider:
    def __init__(self, size_mb):
        self.size = (size_mb * 1024 * 1024 // SECTOR_SIZE) * SECTOR_SIZE
        if self.size < SECTOR_SIZE: raise ValueError("RAM size must be at least 1 sector")
        try: self.memory = bytearray(self.size)
        except MemoryError: raise SystemExit("ERROR: Not enough free memory for provider buffer")
        self.lock = threading.RLock()
        self.leases, self.lease_lock, self.next_lease_id = {}, threading.RLock(), 1
        print("RAM-LINK WINDOWS RAM PROVIDER")
        print(f"Provider buffer: {self.size / 1024 / 1024:.1f} MiB")
        print(f"TCP: {HOST}:{PORT}")

    @staticmethod
    def recv_all(conn, size):
        data = bytearray()
        while len(data) < size:
            chunk = conn.recv(min(MAX_BLOCK, size - len(data)))
            if not chunk: raise ConnectionError("peer disconnected")
            data.extend(chunk)
        return bytes(data)

    def send_header(self, conn, op, offset, length):
        conn.sendall(HEADER.pack(MAGIC, op, offset, length))

    def cleanup(self):
        with self.lease_lock:
            for i in [i for i,x in self.leases.items() if not x.alive()]:
                del self.leases[i]

    def free_region(self, length):
        self.cleanup()
        with self.lease_lock:
            leases = sorted(self.leases.values(), key=lambda x:x.offset)
            cursor = 0
            for lease in leases:
                if cursor + length <= lease.offset: return cursor
                cursor = max(cursor, lease.offset + lease.length)
            return cursor if cursor + length <= self.size else None

    def borrow(self, conn, requested):
        length = ((requested + SECTOR_SIZE - 1) // SECTOR_SIZE) * SECTOR_SIZE
        if length <= 0 or length > self.size: raise ValueError("Invalid borrow size")
        offset = self.free_region(length)
        if offset is None: raise RuntimeError("No free provider RAM")
        with self.lease_lock:
            lease_id = self.next_lease_id
            self.next_lease_id += 1
            self.leases[lease_id] = Lease(lease_id, offset, length)
        with self.lock: self.memory[offset:offset+length] = b"\x00" * length
        payload = LEASE_REPLY.pack(lease_id, offset, length)
        self.send_header(conn, OP_BORROW, lease_id, len(payload))
        conn.sendall(payload)
        print(f"[BORROW] lease={lease_id} size={length/1024/1024:.1f} MiB")

    def get_lease(self, lease_id):
        self.cleanup()
        with self.lease_lock:
            lease = self.leases.get(lease_id)
            if not lease: raise ValueError("Lease missing or expired")
            return lease

    def handle(self, conn, op, offset, length):
        if op == OP_PING:
            self.send_header(conn, OP_PING, 0, 4); conn.sendall(b"PONG"); return
        if op == OP_INFO:
            self.cleanup()
            with self.lease_lock: active = len(self.leases)
            body = (f"RAM-LINK\nversion=4\nprotocol=RML1\nrole=PROVIDER\n"
                    f"platform=WINDOWS\ntransport=TCP\nbuffer_bytes={self.size}\n"
                    f"buffer_mib={self.size/1024/1024:.2f}\nactive_leases={active}\n"
                    f"lease_seconds={LEASE_SECONDS}\n").encode()
            self.send_header(conn, OP_INFO, 0, len(body)); conn.sendall(body); return
        if op == OP_BORROW: self.borrow(conn, length); return
        if op == OP_RELEASE:
            with self.lease_lock:
                if self.leases.pop(offset, None) is None: raise ValueError("Unknown lease")
            self.send_header(conn, OP_RELEASE, offset, 0); return
        if op == OP_KEEPALIVE:
            self.get_lease(offset).keepalive()
            self.send_header(conn, OP_KEEPALIVE, offset, 0); return
        if op in (OP_READ, OP_WRITE):
            if length > MAX_BLOCK: raise ValueError("Transfer exceeds maximum")
            with self.lease_lock:
                lease = next((x for x in self.leases.values()
                              if x.alive() and offset >= x.offset and
                              offset + length <= x.offset + x.length), None)
            if lease is None: raise ValueError("Access is outside an active lease")
            if op == OP_WRITE:
                data = self.recv_all(conn, length)
                with self.lock: self.memory[offset:offset+length] = data
                self.send_header(conn, OP_WRITE, offset, length)
            else:
                with self.lock: data = bytes(self.memory[offset:offset+length])
                self.send_header(conn, OP_READ, offset, length); conn.sendall(data)
            return
        raise ValueError(f"Unknown operation {op}")

    def client(self, conn, address):
        print("[+] Client connected:", address)
        try:
            while True:
                magic, op, offset, length = HEADER.unpack(self.recv_all(conn, HEADER.size))
                if magic != MAGIC: raise ValueError("Invalid protocol magic")
                self.handle(conn, op, offset, length)
        except Exception as exc: print("[-]", address, exc)
        finally: conn.close()

    def start(self):
        server = socket.socket(); server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT)); server.listen(8)
        print("SERVER READY - Android can borrow PC RAM")
        try:
            while True:
                conn, address = server.accept()
                threading.Thread(target=self.client, args=(conn,address), daemon=True).start()
        except KeyboardInterrupt: print("\nStopping provider.")
        finally: server.close()

if __name__ == "__main__":
    mb = int(sys.argv[1]) if len(sys.argv) > 1 else 512
    if mb < 1: raise SystemExit("Usage: python ramlink_memory_provider.py <RAM_MB>")
    RAMProvider(mb).start()
