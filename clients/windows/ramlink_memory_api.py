#!/usr/bin/env python3
"""
RAM-Link application-facing memory API.

This is the first software-facing layer above the RAM-Link wire protocol.
Applications use MemoryRegion.read()/write() instead of knowing RML1,
Android, TCP, leases, or the phone's address.

It is RAM/working-memory access, not a filesystem or storage API.
"""
import argparse
import hashlib
import socket
import struct
from collections import OrderedDict

SERVICE_HOST = "127.0.0.1"
SERVICE_PORT = 19080
PAGE_SIZE = 64 * 1024
MAX_TRANSFER = 1024 * 1024


def recv_all(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(min(MAX_TRANSFER, size - len(data)))
        if not chunk:
            raise ConnectionError("RAM-Link memory service disconnected")
        data.extend(chunk)
    return bytes(data)


class _Service:
    def __init__(self, host, port):
        self.host, self.port = host, port

    def read(self, offset, length):
        if length > MAX_TRANSFER:
            raise ValueError("service read exceeds 1 MiB")
        with socket.create_connection((self.host, self.port), timeout=30) as s:
            s.sendall(f"READ {offset} {length}\n".encode())
            size = struct.unpack("!I", recv_all(s, 4))[0]
            if size != length:
                raise IOError(f"short RAM-Link read: expected {length}, got {size}")
            return recv_all(s, size)

    def write(self, offset, data):
        if len(data) > MAX_TRANSFER:
            raise ValueError("service write exceeds 1 MiB")
        with socket.create_connection((self.host, self.port), timeout=30) as s:
            s.sendall(f"WRITE {offset} {len(data)}\n".encode() + data)
            reply = s.recv(64).decode(errors="replace").strip()
            if reply != "OK":
                raise IOError(reply)


class _Cache:
    def __init__(self, remote_size, cache_bytes):
        self.remote_size = remote_size
        self.max_pages = max(1, cache_bytes // PAGE_SIZE)
        self.pages = OrderedDict()
        self.dirty = set()
        self.hits = self.misses = self.remote_reads = self.remote_writes = 0

    def check(self, offset, length):
        if offset < 0 or length < 0 or offset + length > self.remote_size:
            raise ValueError("memory range is outside the RAM-Link region")

    def load(self, service, page):
        if page in self.pages:
            data = self.pages.pop(page)
            self.pages[page] = data
            self.hits += 1
            return data
        self.misses += 1
        base = page * PAGE_SIZE
        size = min(PAGE_SIZE, self.remote_size - base)
        data = bytearray(service.read(base, size))
        self.remote_reads += 1
        if len(self.pages) >= self.max_pages:
            old, _ = self.pages.popitem(last=False)
            if old in self.dirty:
                self.flush_page(service, old)
                self.dirty.remove(old)
        self.pages[page] = data
        return data

    def flush_page(self, service, page):
        data = self.pages.get(page)
        if data is not None:
            service.write(page * PAGE_SIZE, bytes(data))
            self.remote_writes += 1

    def read(self, service, offset, length):
        self.check(offset, length)
        out = bytearray()
        while length:
            page = offset // PAGE_SIZE
            inside = offset % PAGE_SIZE
            data = self.load(service, page)
            n = min(length, len(data) - inside)
            out.extend(data[inside:inside+n])
            offset += n
            length -= n
        return bytes(out)

    def write(self, service, offset, data):
        self.check(offset, len(data))
        pos = 0
        while pos < len(data):
            page = offset // PAGE_SIZE
            inside = offset % PAGE_SIZE
            page_data = self.load(service, page)
            n = min(len(data) - pos, len(page_data) - inside)
            page_data[inside:inside+n] = data[pos:pos+n]
            self.dirty.add(page)
            self.pages.move_to_end(page)
            offset += n
            pos += n

    def flush(self, service):
        for page in list(self.dirty):
            self.flush_page(service, page)
        self.dirty.clear()


class MemoryRegion:
    """A byte-addressable RAM-Link working-memory region."""

    def __init__(self, memory, offset, size):
        self._memory, self.offset, self.size = memory, offset, size
        self.closed = False

    def _check(self, offset, length):
        if self.closed:
            raise RuntimeError("memory region is closed")
        if offset < 0 or length < 0 or offset + length > self.size:
            raise ValueError("operation is outside this memory region")

    def read(self, offset, length):
        self._check(offset, length)
        return self._memory._read(self.offset + offset, length)

    def write(self, offset, data):
        self._check(offset, len(data))
        self._memory._write(self.offset + offset, bytes(data))

    def fill(self, value=0):
        if not 0 <= value <= 255:
            raise ValueError("fill value must be 0..255")
        chunk = bytes([value]) * MAX_TRANSFER
        left = self.size
        pos = 0
        while left:
            n = min(left, MAX_TRANSFER)
            self.write(pos, chunk[:n])
            pos += n
            left -= n

    def close(self):
        self.closed = True


class RAMLinkMemory:
    """
    Application-facing RAM-Link memory client.

    Example:
        memory = RAMLinkMemory(256)
        region = memory.allocate(16 * 1024 * 1024)
        region.write(0, b"hello")
        assert region.read(0, 5) == b"hello"
        memory.flush()
        region.close()
        memory.close()
    """

    def __init__(self, remote_mb=256, cache_mb=32,
                 host=SERVICE_HOST, port=SERVICE_PORT):
        if remote_mb < 1 or cache_mb < 1:
            raise ValueError("remote_mb and cache_mb must be positive")
        self.service = _Service(host, port)
        self.cache = _Cache(remote_mb * 1024 * 1024, cache_mb * 1024 * 1024)
        self.next_offset = 0
        self.regions = []

    def allocate(self, size):
        if size <= 0:
            raise ValueError("allocation size must be positive")
        size = int(size)
        if self.next_offset + size > self.cache.remote_size:
            raise MemoryError("RAM-Link remote memory exhausted")
        region = MemoryRegion(self, self.next_offset, size)
        self.next_offset += size
        self.regions.append(region)
        return region

    def _read(self, offset, length):
        return self.cache.read(self.service, offset, length)

    def _write(self, offset, data):
        self.cache.write(self.service, offset, data)

    def flush(self):
        self.cache.flush(self.service)

    def stats(self):
        total = self.cache.hits + self.cache.misses
        return {
            "remote_mib": round(self.cache.remote_size / 1024 / 1024, 2),
            "cache_mib": round(self.cache.max_pages * PAGE_SIZE / 1024 / 1024, 2),
            "cache_hits": self.cache.hits,
            "cache_misses": self.cache.misses,
            "hit_rate_percent": round(self.cache.hits / total * 100, 2) if total else 0,
            "remote_reads": self.cache.remote_reads,
            "remote_writes": self.cache.remote_writes,
        }

    def close(self):
        self.flush()
        for region in self.regions:
            region.close()


def main():
    parser = argparse.ArgumentParser(description="Test RAM-Link as application memory")
    parser.add_argument("--remote-mb", type=int, default=256)
    parser.add_argument("--cache-mb", type=int, default=32)
    parser.add_argument("--test-mb", type=int, default=8)
    parser.add_argument("--host", default=SERVICE_HOST)
    parser.add_argument("--port", type=int, default=SERVICE_PORT)
    args = parser.parse_args()

    memory = RAMLinkMemory(args.remote_mb, args.cache_mb, args.host, args.port)
    try:
        size = min(args.test_mb * 1024 * 1024, memory.cache.remote_size)
        region = memory.allocate(size)

        pattern = bytes((i * 31 + 7) % 256 for i in range(size))
        region.write(0, pattern)
        memory.flush()

        result = region.read(0, size)
        expected = hashlib.sha256(pattern).hexdigest()
        actual = hashlib.sha256(result).hexdigest()

        print("RAM-LINK APPLICATION MEMORY TEST")
        print(f"Allocated: {size / 1024 / 1024:.1f} MiB")
        print(f"SHA256: {'PASS' if expected == actual else 'FAIL'}")
        for key, value in memory.stats().items():
            print(f"{key}={value}")

        if expected != actual:
            raise SystemExit("APPLICATION MEMORY TEST FAILED")
        print("APPLICATION MEMORY API: PASS")
    finally:
        memory.close()


if __name__ == "__main__":
    main()
