#!/usr/bin/env python3
"""RAM-Link Android remote-memory cache.

This is the next integration layer after transport validation. It provides a
user-space byte-addressable cache backed by PC RAM. It is intentionally NOT
presented as native Android physical RAM: Android applications do not see it
as ordinary heap memory.

Usage:
    python android/termux/remote_cache.py <PC_IP> --mb 256 --cache-mb 32
"""
import argparse, collections, hashlib, socket, struct, threading

PORT = 18080
MAGIC = b"RML1"
HEADER = struct.Struct("!4sBQI")
LEASE_REPLY = struct.Struct("!QQQ")
MAX_BLOCK = 1024 * 1024
PAGE = 64 * 1024

OP_READ, OP_WRITE, OP_BORROW, OP_RELEASE, OP_KEEPALIVE = 2, 3, 8, 9, 10


def recv_all(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(min(MAX_BLOCK, size - len(data)))
        if not chunk:
            raise ConnectionError("remote provider disconnected")
        data.extend(chunk)
    return bytes(data)


def request(sock, op, offset=0, length=0, payload=b""):
    sock.sendall(HEADER.pack(MAGIC, op, offset, length))
    if payload:
        sock.sendall(payload)
    magic, _, _, rlen = HEADER.unpack(recv_all(sock, HEADER.size))
    if magic != MAGIC:
        raise ValueError("Invalid RML1 response")
    return recv_all(sock, rlen) if rlen else b""


class RemoteCache:
    def __init__(self, host, remote_mb, cache_mb):
        self.sock = socket.socket()
        self.sock.settimeout(20)
        self.sock.connect((host, PORT))

        body = request(self.sock, OP_BORROW, length=remote_mb * 1024 * 1024)
        self.lease_id, self.base, self.remote_size = LEASE_REPLY.unpack(body)

        self.capacity = max(1, (cache_mb * 1024 * 1024) // PAGE)
        self.pages = collections.OrderedDict()
        self.lock = threading.RLock()
        self.hits = 0
        self.misses = 0

    def remote_read(self, absolute_offset, length):
        out = bytearray()
        for pos in range(0, length, MAX_BLOCK):
            n = min(MAX_BLOCK, length - pos)
            out.extend(request(self.sock, OP_READ,
                               self.base + absolute_offset + pos, n))
        return bytes(out)

    def remote_write(self, absolute_offset, data):
        for pos in range(0, len(data), MAX_BLOCK):
            chunk = data[pos:pos + MAX_BLOCK]
            request(self.sock, OP_WRITE,
                    self.base + absolute_offset + pos, len(chunk), chunk)

    def load_page(self, page_no):
        data = self.remote_read(page_no * PAGE, PAGE)
        self.pages[page_no] = bytearray(data)
        self.pages.move_to_end(page_no)

        while len(self.pages) > self.capacity:
            self.pages.popitem(last=False)

    def read(self, offset, length):
        if offset < 0 or offset + length > self.remote_size:
            raise ValueError("read outside remote allocation")

        out = bytearray()
        with self.lock:
            while length:
                page_no = offset // PAGE
                inside = offset % PAGE
                n = min(length, PAGE - inside)

                if page_no in self.pages:
                    self.hits += 1
                    page = self.pages[page_no]
                    self.pages.move_to_end(page_no)
                else:
                    self.misses += 1
                    self.load_page(page_no)
                    page = self.pages[page_no]

                out.extend(page[inside:inside + n])
                offset += n
                length -= n
        return bytes(out)

    def write(self, offset, data):
        if offset < 0 or offset + len(data) > self.remote_size:
            raise ValueError("write outside remote allocation")

        with self.lock:
            pos = 0
            while pos < len(data):
                page_no = (offset + pos) // PAGE
                inside = (offset + pos) % PAGE
                n = min(len(data) - pos, PAGE - inside)

                if page_no not in self.pages:
                    self.misses += 1
                    self.load_page(page_no)
                else:
                    self.hits += 1

                page = self.pages[page_no]
                page[inside:inside + n] = data[pos:pos + n]
                self.remote_write(page_no * PAGE, page)
                self.pages.move_to_end(page_no)
                pos += n

    def status(self):
        return {
            "remote_bytes": self.remote_size,
            "remote_mib": round(self.remote_size / 1024 / 1024, 1),
            "cached_pages": len(self.pages),
            "cache_mib": round(len(self.pages) * PAGE / 1024 / 1024, 1),
            "cache_hits": self.hits,
            "cache_misses": self.misses,
        }

    def close(self):
        try:
            request(self.sock, OP_RELEASE, self.lease_id)
        except Exception:
            pass
        self.sock.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("pc_ip")
    p.add_argument("--mb", type=int, default=256)
    p.add_argument("--cache-mb", type=int, default=32)
    a = p.parse_args()

    cache = RemoteCache(a.pc_ip, a.mb, a.cache_mb)
    print(f"Remote memory: {cache.remote_size / 1024 / 1024:.1f} MiB")
    print(f"Local cache: {a.cache_mb} MiB")

    try:
        pattern = (bytes(range(256)) * ((PAGE // 256) + 1))[:PAGE]
        cache.write(0, pattern)
        check = cache.read(0, PAGE)
        print("CACHE INTEGRITY:", "PASS" if check == pattern else "FAIL")
        print("STATUS:", cache.status())
    finally:
        cache.close()


if __name__ == "__main__":
    main()
