#!/usr/bin/env python3
"""RAM-Link Windows continuous remote-memory service.

Keeps one borrowed Android RAM region alive and exposes it through a small
localhost API. This is volatile working memory, not persistent storage.
"""
import argparse
import socket
import struct
import threading
import time

RML_MAGIC = b"RML1"
RML_HEADER = struct.Struct("!4sBQI")
LOCAL_HOST = "127.0.0.1"
LOCAL_PORT = 19080
MAX_TRANSFER = 1024 * 1024

OP_READ = 2
OP_WRITE = 3
OP_BORROW = 8
OP_RELEASE = 9
OP_KEEPALIVE = 10
LEASE_REPLY = struct.Struct("!QQQ")


def recv_all(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(min(MAX_TRANSFER, size - len(data)))
        if not chunk:
            raise ConnectionError("peer disconnected")
        data.extend(chunk)
    return bytes(data)


def rml_request(sock, op, offset=0, length=0, payload=b""):
    sock.sendall(RML_HEADER.pack(RML_MAGIC, op, offset, length))
    if payload:
        sock.sendall(payload)
    magic, rop, roff, rlen = RML_HEADER.unpack(
        recv_all(sock, RML_HEADER.size)
    )
    if magic != RML_MAGIC:
        raise ValueError("Invalid RAM-Link response magic")
    return rop, roff, recv_all(sock, rlen) if rlen else b""


class RemoteMemory:
    def __init__(self, host, port, megabytes, keepalive_seconds):
        self.host = host
        self.port = port
        self.megabytes = megabytes
        self.keepalive_seconds = keepalive_seconds
        self.sock = None
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.lease_id = 0
        self.base_offset = 0
        self.length = 0
        self.started = None
        self.last_keepalive = None
        self.last_error = None
        self.reconnects = 0

    def _borrow_new_socket(self):
        sock = socket.socket()
        sock.settimeout(20)
        try:
            sock.connect((self.host, self.port))
            _, _, body = rml_request(
                sock, OP_BORROW,
                length=self.megabytes * 1024 * 1024
            )
            if len(body) != LEASE_REPLY.size:
                raise ValueError("Invalid BORROW reply")
            lease_id, base_offset, length = LEASE_REPLY.unpack(body)
            return sock, lease_id, base_offset, length
        except Exception:
            sock.close()
            raise

    def connect_and_borrow(self):
        sock, lease_id, base_offset, length = self._borrow_new_socket()
        with self.lock:
            self.sock = sock
            self.lease_id = lease_id
            self.base_offset = base_offset
            self.length = length
            now = time.time()
            self.started = now
            self.last_keepalive = now
            self.last_error = None
        print(
            f"[RAM-LINK] borrowed {length / 1024 / 1024:.1f} MiB "
            f"lease={lease_id} offset={base_offset}"
        )

    def _mark_disconnected(self, exc):
        old = self.sock
        self.sock = None
        self.lease_id = 0
        self.base_offset = 0
        self.last_error = str(exc)
        if old:
            try:
                old.close()
            except OSError:
                pass

    def _reconnect(self):
        # A reconnect receives a fresh volatile region. Cached application
        # data must therefore be treated as invalid by the caller.
        sock, lease_id, base_offset, length = self._borrow_new_socket()
        self.sock = sock
        self.lease_id = lease_id
        self.base_offset = base_offset
        self.length = length
        self.last_keepalive = time.time()
        self.reconnects += 1
        self.last_error = None
        print(
            f"[RAM-LINK] reconnected with fresh lease={lease_id} "
            f"size={length / 1024 / 1024:.1f} MiB"
        )

    def _request_with_reconnect(self, op, offset=0, length=0, payload=b""):
        try:
            return rml_request(self.sock, op, offset, length, payload)
        except Exception as first_error:
            self._mark_disconnected(first_error)
            self._reconnect()
            return rml_request(self.sock, op, offset, length, payload)

    def keepalive(self):
        with self.lock:
            if not self.sock or not self.lease_id:
                return
            try:
                rml_request(self.sock, OP_KEEPALIVE, self.lease_id)
                self.last_keepalive = time.time()
                self.last_error = None
            except Exception as exc:
                self._mark_disconnected(exc)
                raise

    def read(self, offset, length):
        if offset < 0 or length < 0 or offset + length > self.length:
            raise ValueError("Read outside borrowed region")
        output = bytearray()
        with self.lock:
            for pos in range(offset, offset + length, MAX_TRANSFER):
                n = min(MAX_TRANSFER, offset + length - pos)
                _, _, body = self._request_with_reconnect(
                    OP_READ, self.base_offset + pos, n
                )
                if len(body) != n:
                    raise IOError("Short remote read")
                output.extend(body)
        return bytes(output)

    def write(self, offset, data):
        if offset < 0 or offset + len(data) > self.length:
            raise ValueError("Write outside borrowed region")
        with self.lock:
            pos = 0
            while pos < len(data):
                n = min(MAX_TRANSFER, len(data) - pos)
                chunk = data[pos:pos + n]
                self._request_with_reconnect(
                    OP_WRITE, self.base_offset + offset + pos, n, chunk
                )
                pos += n

    def status(self):
        with self.lock:
            return {
                "connected": bool(self.sock and self.lease_id),
                "lease_id": self.lease_id,
                "size_bytes": self.length,
                "size_mib": round(self.length / 1024 / 1024, 2),
                "uptime_seconds": round(
                    time.time() - self.started, 1
                ) if self.started else 0,
                "last_keepalive": self.last_keepalive,
                "last_error": self.last_error,
                "reconnects": self.reconnects,
                "android_host": self.host,
                "android_port": self.port,
                "volatile": True,
            }

    def release(self):
        with self.lock:
            sock = self.sock
            lease_id = self.lease_id
            self.sock = None
            self.lease_id = 0
        if sock and lease_id:
            try:
                rml_request(sock, OP_RELEASE, lease_id)
            except Exception:
                pass
            sock.close()

    def keepalive_loop(self):
        while not self.stop_event.wait(self.keepalive_seconds):
            try:
                self.keepalive()
                print(f"[RAM-LINK] keepalive lease={self.lease_id}")
            except Exception as exc:
                print("[RAM-LINK] keepalive failed:", exc)
                # Do not silently invent persistence: the next memory request
                # can acquire a fresh volatile lease through reconnect logic.


class LocalApi:
    def __init__(self, memory):
        self.memory = memory

    def handle(self, conn):
        line = conn.recv(4096).decode("utf-8", "replace").strip()
        if not line:
            return
        parts = line.split()
        command = parts[0].upper()

        if command in ("HELLO", "PING"):
            conn.sendall(b"RAM-LINK LOCAL API 2\n")
            return

        if command in ("SIZE", "STATUS"):
            s = self.memory.status()
            if command == "SIZE":
                conn.sendall(f"{s['size_bytes']}\n".encode())
            else:
                conn.sendall(
                    ("\n".join(f"{k}={v}" for k, v in s.items()) + "\n").encode()
                )
            return

        if command == "READ" and len(parts) == 3:
            offset = int(parts[1])
            length = int(parts[2])
            if length > MAX_TRANSFER:
                raise ValueError("Local READ is limited to 1 MiB")
            data = self.memory.read(offset, length)
            conn.sendall(struct.pack("!I", len(data)) + data)
            return

        if command == "WRITE" and len(parts) == 3:
            offset = int(parts[1])
            length = int(parts[2])
            if length > MAX_TRANSFER:
                raise ValueError("Local WRITE is limited to 1 MiB")
            data = recv_all(conn, length)
            self.memory.write(offset, data)
            conn.sendall(b"OK\n")
            return

        conn.sendall(b"ERROR invalid command\n")

    def serve(self):
        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((LOCAL_HOST, LOCAL_PORT))
        server.listen(8)
        print(f"[RAM-LINK] local API listening on {LOCAL_HOST}:{LOCAL_PORT}")
        while not self.memory.stop_event.is_set():
            server.settimeout(1)
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            threading.Thread(
                target=self.client, args=(conn,), daemon=True
            ).start()
        server.close()

    def client(self, conn):
        try:
            self.handle(conn)
        except Exception as exc:
            try:
                conn.sendall(f"ERROR {exc}\n".encode())
            except OSError:
                pass
        finally:
            conn.close()


def main():
    p = argparse.ArgumentParser(
        description="Keep Android RAM continuously available to Windows."
    )
    p.add_argument("host")
    p.add_argument("--mb", type=int, default=256)
    p.add_argument("--port", type=int, default=18080)
    p.add_argument("--keepalive", type=int, default=30)
    a = p.parse_args()

    if a.mb < 1:
        p.error("--mb must be at least 1")
    if not 5 <= a.keepalive <= 110:
        p.error("--keepalive must be between 5 and 110 seconds")

    memory = RemoteMemory(a.host, a.port, a.mb, a.keepalive)
    try:
        memory.connect_and_borrow()
        threading.Thread(
            target=memory.keepalive_loop, daemon=True
        ).start()
        LocalApi(memory).serve()
    except KeyboardInterrupt:
        print("\n[RAM-LINK] stopping")
    except Exception as exc:
        print("[RAM-LINK] startup failed:", exc)
        raise SystemExit(1)
    finally:
        memory.stop_event.set()
        memory.release()
        print("[RAM-LINK] released remote memory")


if __name__ == "__main__":
    main()
