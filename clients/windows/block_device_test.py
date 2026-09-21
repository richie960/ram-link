#!/usr/bin/env python3
import hashlib
import socket
import struct
import time

from ramlink_client import discover_phone

PORT = 8081
MAGIC = b"RML1"
HEADER = struct.Struct("!4sBQI")
OP_BLOCK_INFO, OP_BLOCK_READ, OP_BLOCK_WRITE = 5, 6, 7
SECTOR_SIZE = 512
MAX_BLOCK = 1024 * 1024


def recv_all(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(min(MAX_BLOCK, size - len(data)))
        if not chunk:
            raise ConnectionError("RAM-Link server disconnected")
        data.extend(chunk)
    return bytes(data)


class RAMLinkBlockDevice:
    def __init__(self, host):
        self.host = host
        self.s = socket.socket()
        self.s.settimeout(15)
        self.s.connect((host, PORT))

        _, _, data = self.request(OP_BLOCK_INFO)
        self.sector_size, self.sector_count = struct.unpack("!QQ", data)

        print("Connected to:", host)
        print("Sector size:", self.sector_size)
        print("Sector count:", self.sector_count)
        print("Device size:", self.sector_size * self.sector_count, "bytes")

    def request(self, op, offset=0, length=0, payload=b""):
        self.s.sendall(HEADER.pack(MAGIC, op, offset, length))
        if payload:
            self.s.sendall(payload)

        magic, rop, roff, rlen = HEADER.unpack(recv_all(self.s, HEADER.size))
        if magic != MAGIC:
            raise ValueError("Invalid response")

        return rop, roff, recv_all(self.s, rlen) if rlen else b""

    def read(self, sector, count):
        out = bytearray()
        per = MAX_BLOCK // self.sector_size

        while count:
            n = min(count, per)
            out.extend(self.request(OP_BLOCK_READ, sector, n)[2])
            sector += n
            count -= n

        return bytes(out)

    def write(self, sector, data):
        if len(data) % self.sector_size:
            raise ValueError("Unaligned write")

        count = len(data) // self.sector_size
        per = MAX_BLOCK // self.sector_size
        position = 0

        while count:
            n = min(count, per)
            size = n * self.sector_size
            self.request(
                OP_BLOCK_WRITE,
                sector,
                n,
                data[position:position + size],
            )
            sector += n
            position += size
            count -= n


def main():
    host = discover_phone()

    if not host:
        manual = input("Enter phone IP manually (or press Enter to exit): ").strip()
        if not manual:
            return
        host = manual

    device = RAMLinkBlockDevice(host)

    try:
        print("\nTEST 1: Read sector 0")
        print(device.read(0, 1).hex())

        print("\nTEST 2: Write/read sector 100")
        block = bytearray(SECTOR_SIZE)
        message = b"RAM-LINK BLOCK DEVICE TEST"
        block[:len(message)] = message
        device.write(100, bytes(block))
        returned = device.read(100, 1)
        print(
            "BLOCK TEST:",
            "PASS" if returned == bytes(block) else "FAIL",
        )

        print("\nTEST 3: Multi-sector integrity")
        count = 2048
        pattern = bytes(i % 256 for i in range(count * SECTOR_SIZE))

        start = time.perf_counter()
        device.write(1000, pattern)
        write_time = time.perf_counter() - start

        start = time.perf_counter()
        returned = device.read(1000, count)
        read_time = time.perf_counter() - start

        expected = hashlib.sha256(pattern).hexdigest()
        actual = hashlib.sha256(returned).hexdigest()

        print("Size:", len(pattern) / 1024 / 1024, "MB")
        print("Write:", f"{write_time:.3f} s")
        print("Read:", f"{read_time:.3f} s")
        print("Expected:", expected)
        print("Returned:", actual)
        print(
            "MULTI-SECTOR TEST:",
            "PASS" if expected == actual else "FAIL",
        )
    finally:
        device.s.close()


if __name__ == "__main__":
    main()
