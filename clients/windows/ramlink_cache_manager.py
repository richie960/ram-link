#!/usr/bin/env python3
"""
RAM-Link active remote-memory cache.

This layer gives Windows software a simple cache API backed by the continuously
borrowed Android RAM service. It uses fixed-size pages and an LRU policy.

It is deliberately an application-level memory/cache layer. It does NOT claim
to add physical RAM to the Windows kernel memory manager.
"""
import argparse
import hashlib
import socket
import struct
import threading
import time
from collections import OrderedDict

HOST = "127.0.0.1"
PORT = 19080
PAGE_SIZE = 64 * 1024
MAX_TRANSFER = 1024 * 1024


def recv_all(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(min(MAX_TRANSFER, size - len(data)))
        if not chunk:
            raise ConnectionError("memory service disconnected")
        data.extend(chunk)
    return bytes(data)


class RemoteAPI:
    def __init__(self, host=HOST, port=PORT):
        self.host = host
        self.port = port

    def call(self, line, payload=b"", expect_bytes=False):
        sock = socket.socket()
        sock.settimeout(30)
        try:
            sock.connect((self.host, self.port))
            sock.sendall(line.encode() + b"\n" + payload)
            if expect_bytes:
                size = struct.unpack("!I", recv_all(sock, 4))[0]
                return recv_all(sock, size)
            return sock.recv(MAX_TRANSFER).decode(errors="replace")
        finally:
            sock.close()

    def read(self, offset, length):
        return self.call(
            f"READ {offset} {length}", expect_bytes=True
        )

    def write(self, offset, data):
        result = self.call(
            f"WRITE {offset} {len(data)}", payload=data
        )
        if not result.startswith("OK"):
            raise IOError(result.strip())


class RemoteMemoryCache:
    def __init__(self, capacity_mb, remote_size, page_size=PAGE_SIZE):
        self.capacity = capacity_mb * 1024 * 1024
        self.remote_size = remote_size
        self.page_size = page_size
        self.max_pages = self.capacity // page_size
        if self.max_pages < 1:
            raise ValueError("cache capacity is smaller than one page")

        self.pages = OrderedDict()
        self.dirty = set()
        self.lock = threading.RLock()

        self.hits = 0
        self.misses = 0
        self.remote_reads = 0
        self.remote_writes = 0
        self.evictions = 0

    def _check(self, offset, length):
        if offset < 0 or length < 0 or offset + length > self.remote_size:
            raise ValueError("range outside remote memory")

    def _page(self, page_number):
        return page_number * self.page_size

    def _load_page(self, api, page_number):
        if page_number in self.pages:
            data = self.pages.pop(page_number)
            self.pages[page_number] = data
            self.hits += 1
            return data

        self.misses += 1
        offset = self._page(page_number)
        length = min(self.page_size, self.remote_size - offset)
        data = bytearray(api.read(offset, length))
        self.remote_reads += 1

        if len(self.pages) >= self.max_pages:
            old_page, _ = self.pages.popitem(last=False)
            if old_page in self.dirty:
                self._flush_page(api, old_page)
                self.dirty.discard(old_page)
            self.evictions += 1

        self.pages[page_number] = data
        return data

    def _flush_page(self, api, page_number):
        data = self.pages.get(page_number)
        if data is None:
            return
        api.write(self._page(page_number), bytes(data))
        self.remote_writes += 1

    def read(self, api, offset, length):
        self._check(offset, length)
        output = bytearray()

        with self.lock:
            while length:
                page = offset // self.page_size
                inside = offset % self.page_size
                data = self._load_page(api, page)
                n = min(length, len(data) - inside)
                output.extend(data[inside:inside + n])
                offset += n
                length -= n

        return bytes(output)

    def write(self, api, offset, data):
        self._check(offset, len(data))
        pos = 0

        with self.lock:
            while pos < len(data):
                page = offset // self.page_size
                inside = offset % self.page_size
                page_data = self._load_page(api, page)
                n = min(len(data) - pos, len(page_data) - inside)
                page_data[inside:inside + n] = data[pos:pos + n]
                self.dirty.add(page)
                self.pages.move_to_end(page)
                offset += n
                pos += n

    def flush(self, api):
        with self.lock:
            for page in list(self.dirty):
                self._flush_page(api, page)
            self.dirty.clear()

    def stats(self):
        with self.lock:
            total = self.hits + self.misses
            hit_rate = (self.hits / total * 100) if total else 0
            return {
                "page_size": self.page_size,
                "cached_pages": len(self.pages),
                "cache_capacity": self.capacity,
                "cache_mib": self.capacity / 1024 / 1024,
                "remote_size": self.remote_size,
                "remote_mib": self.remote_size / 1024 / 1024,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate_percent": round(hit_rate, 2),
                "remote_reads": self.remote_reads,
                "remote_writes": self.remote_writes,
                "evictions": self.evictions,
                "dirty_pages": len(self.dirty),
            }


def parse_size(text):
    text = text.upper()
    units = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}
    for suffix, multiplier in units.items():
        if text.endswith(suffix):
            return int(float(text[:-1]) * multiplier)
    return int(text)


def main():
    p = argparse.ArgumentParser(
        description="Test the RAM-Link active remote-memory cache."
    )
    p.add_argument("--remote-mb", type=int, default=256)
    p.add_argument("--cache-mb", type=int, default=32)
    p.add_argument("--test-mb", type=int, default=64)
    p.add_argument("--host", default=HOST)
    p.add_argument("--port", type=int, default=PORT)
    args = p.parse_args()

    api = RemoteAPI(args.host, args.port)
    remote_size = args.remote_mb * 1024 * 1024
    cache = RemoteMemoryCache(args.cache_mb, remote_size)

    test_size = min(args.test_mb * 1024 * 1024, remote_size)
    pattern = bytes((i * 31 + 7) % 256 for i in range(test_size))

    print("RAM-LINK ACTIVE MEMORY CACHE")
    print(f"Remote memory: {remote_size / 1024 / 1024:.1f} MiB")
    print(f"Local cache:   {args.cache_mb} MiB")
    print(f"Test data:     {test_size / 1024 / 1024:.1f} MiB")

    start = time.perf_counter()
    cache.write(api, 0, pattern)
    cache.flush(api)
    write_time = time.perf_counter() - start

    start = time.perf_counter()
    result = cache.read(api, 0, test_size)
    read_time = time.perf_counter() - start

    expected = hashlib.sha256(pattern).hexdigest()
    actual = hashlib.sha256(result).hexdigest()

    print(f"WRITE: {write_time:.2f}s")
    print(f"READ:  {read_time:.2f}s")
    print(f"SHA256: {'PASS' if expected == actual else 'FAIL'}")
    print("CACHE STATS:")
    for key, value in cache.stats().items():
        print(f"  {key}={value}")

    if expected != actual:
        raise SystemExit("REMOTE CACHE TEST FAILED")

    print("ACTIVE REMOTE MEMORY CACHE: PASS")


if __name__ == "__main__":
    main()
