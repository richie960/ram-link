#!/usr/bin/env python3
"""RAM-Link Android/Termux borrower for a PC RAM provider."""
import hashlib, socket, struct, sys, threading

PORT = 18080
MAGIC = b"RML1"
HEADER = struct.Struct("!4sBQI")
LEASE_REPLY = struct.Struct("!QQQ")
MAX_BLOCK = 1024 * 1024
OP_READ, OP_WRITE, OP_BORROW, OP_RELEASE, OP_KEEPALIVE = 2, 3, 8, 9, 10

def recv_all(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(min(MAX_BLOCK, size-len(data)))
        if not chunk: raise ConnectionError("peer disconnected")
        data.extend(chunk)
    return bytes(data)

def request(sock, op, offset=0, length=0, payload=b""):
    sock.sendall(HEADER.pack(MAGIC, op, offset, length))
    if payload: sock.sendall(payload)
    magic, rop, roff, rlen = HEADER.unpack(recv_all(sock, HEADER.size))
    if magic != MAGIC: raise ValueError("Invalid RML1 response")
    return rop, roff, recv_all(sock, rlen) if rlen else b""

if len(sys.argv) < 2:
    raise SystemExit("Usage: python client.py <PC_IP> [MB]")

host = sys.argv[1]
mb = int(sys.argv[2]) if len(sys.argv) > 2 else 256
size = mb * 1024 * 1024
sock = socket.socket(); sock.settimeout(20); sock.connect((host, PORT))

_, _, body = request(sock, OP_BORROW, length=size)
lease_id, base, length = LEASE_REPLY.unpack(body)
print(f"Borrowed {length/1024/1024:.1f} MiB from PC, lease={lease_id}")

stop = threading.Event()
def keepalive():
    while not stop.wait(30):
        request(sock, OP_KEEPALIVE, lease_id)
        print("KEEPALIVE ok")
threading.Thread(target=keepalive, daemon=True).start()

try:
    pattern = (bytes(range(256)) * ((size // 256) + 1))[:size]
    for offset in range(0, size, MAX_BLOCK):
        n = min(MAX_BLOCK, size-offset)
        request(sock, OP_WRITE, base+offset, n, pattern[offset:offset+n])
    out = bytearray()
    for offset in range(0, size, MAX_BLOCK):
        n = min(MAX_BLOCK, size-offset)
        out.extend(request(sock, OP_READ, base+offset, n)[2])
    ok = hashlib.sha256(out).digest() == hashlib.sha256(pattern).digest()
    print("PC -> Android remote-memory integrity:", "PASS" if ok else "FAIL")
finally:
    stop.set()
    try: request(sock, OP_RELEASE, lease_id)
    except Exception: pass
    sock.close()
