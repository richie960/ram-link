#!/usr/bin/env python3
"""RAMLink symmetric mesh MVP.

Each node can serve bounded application-owned byte objects and also connect to
other nodes as a client. This is NOT transparent physical RAM or a paging
system. Do not expose arbitrary process/kernel memory.

Protocol: fixed binary frame header + JSON control messages or raw block bytes.
Non-loopback listeners require TLS to avoid sending the bearer token in clear.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import ssl
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

MAGIC = b"RML1"
VERSION = 1
HEADER = struct.Struct("!4sBBIQ")  # magic, version, type, payload length, request ID
MAX_FRAME = 1 * 1024 * 1024
MAX_KEY_BYTES = 200
META_LEN = struct.Struct("!I")

AUTH, AUTH_OK, ERROR, PUT, GET, LIST, STATS, PING, PONG, DATA, OK = range(1, 12)


class ProtocolError(Exception):
    pass


class CapacityError(Exception):
    pass


def pack_frame(msg_type: int, request_id: int, payload: bytes = b"") -> bytes:
    if len(payload) > MAX_FRAME:
        raise ProtocolError("frame too large")
    return HEADER.pack(MAGIC, VERSION, msg_type, len(payload), request_id) + payload


async def read_frame(reader: asyncio.StreamReader) -> Tuple[int, int, bytes]:
    raw = await reader.readexactly(HEADER.size)
    magic, version, msg_type, size, request_id = HEADER.unpack(raw)
    if magic != MAGIC or version != VERSION:
        raise ProtocolError("invalid magic/version")
    if size > MAX_FRAME:
        raise ProtocolError("frame exceeds maximum size")
    return msg_type, request_id, await reader.readexactly(size)


def encode_meta_data(meta: dict, data: bytes) -> bytes:
    encoded = json.dumps(meta, separators=(",", ":"), sort_keys=True).encode()
    payload = META_LEN.pack(len(encoded)) + encoded + data
    if len(payload) > MAX_FRAME:
        raise ProtocolError("metadata plus data exceeds frame limit")
    return payload


def decode_meta_data(payload: bytes) -> Tuple[dict, bytes]:
    if len(payload) < META_LEN.size:
        raise ProtocolError("missing metadata length")
    (size,) = META_LEN.unpack(payload[:META_LEN.size])
    if size > len(payload) - META_LEN.size:
        raise ProtocolError("invalid metadata length")
    try:
        meta = json.loads(payload[META_LEN.size:META_LEN.size + size])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("invalid metadata JSON") from exc
    if not isinstance(meta, dict):
        raise ProtocolError("metadata must be an object")
    return meta, payload[META_LEN.size + size:]


def validate_key(key: str) -> str:
    if not isinstance(key, str) or not key or len(key.encode("utf-8")) > MAX_KEY_BYTES:
        raise ValueError(f"key must be 1..{MAX_KEY_BYTES} UTF-8 bytes")
    if any(ord(ch) < 32 for ch in key):
        raise ValueError("control characters are not allowed in keys")
    return key


@dataclass
class ObjectRecord:
    data: bytes
    created_at: float
    sha256: str


class ObjectPool:
    """Bounded in-process pool; accepts only explicit object PUT operations."""
    def __init__(self, capacity_bytes: int):
        if capacity_bytes <= 0:
            raise ValueError("capacity must be positive")
        self.capacity_bytes = capacity_bytes
        self._objects: Dict[str, ObjectRecord] = {}
        self._used = 0

    @property
    def used_bytes(self) -> int:
        return self._used

    def put(self, key: str, data: bytes) -> dict:
        key = validate_key(key)
        if not isinstance(data, bytes):
            raise TypeError("data must be bytes")
        if len(data) > MAX_FRAME - 4096:
            raise CapacityError("object exceeds single-frame limit")
        old = self._objects.get(key)
        projected = self._used - (len(old.data) if old else 0) + len(data)
        if projected > self.capacity_bytes:
            raise CapacityError("pool capacity would be exceeded")
        digest = hashlib.sha256(data).hexdigest()
        self._objects[key] = ObjectRecord(data=data, created_at=time.time(), sha256=digest)
        self._used = projected
        return {"key": key, "size": len(data), "sha256": digest}

    def get(self, key: str) -> Tuple[bytes, dict]:
        key = validate_key(key)
        rec = self._objects.get(key)
        if rec is None:
            raise KeyError("object not found")
        # Re-check before returning; detects accidental in-process corruption.
        actual = hashlib.sha256(rec.data).hexdigest()
        if actual != rec.sha256:
            raise ProtocolError("stored object integrity check failed")
        return rec.data, {"key": key, "size": len(rec.data), "sha256": rec.sha256}

    def listing(self) -> list:
        return [
            {"key": key, "size": len(rec.data), "sha256": rec.sha256,
             "created_at": rec.created_at}
            for key, rec in sorted(self._objects.items())
        ]

    def stats(self) -> dict:
        return {
            "objects": len(self._objects),
            "used_bytes": self._used,
            "capacity_bytes": self.capacity_bytes,
            "available_bytes": self.capacity_bytes - self._used,
        }


class MeshServer:
    def __init__(self, token: str, capacity_bytes: int):
        if not token or len(token) < 16:
            raise ValueError("token must contain at least 16 characters")
        self.token = token.encode()
        self.pool = ObjectPool(capacity_bytes)
        self.started_at = time.time()
        self.bytes_in = 0
        self.bytes_out = 0
        self.requests = 0

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        authenticated = False
        current_request_id = 0
        try:
            while True:
                msg_type, request_id, payload = await read_frame(reader)
                current_request_id = request_id
                if not authenticated:
                    if msg_type != AUTH or not __import__("hmac").compare_digest(payload, self.token):
                        writer.write(pack_frame(ERROR, request_id, b"authentication failed"))
                        await writer.drain()
                        return
                    authenticated = True
                    writer.write(pack_frame(AUTH_OK, request_id, b"RML1"))
                    await writer.drain()
                    continue

                self.requests += 1
                if msg_type == PUT:
                    meta, data = decode_meta_data(payload)
                    result = self.pool.put(meta.get("key"), data)
                    self.bytes_in += len(data)
                    writer.write(pack_frame(OK, request_id, json.dumps(result).encode()))
                elif msg_type == GET:
                    meta = json.loads(payload)
                    data, result = self.pool.get(meta.get("key"))
                    self.bytes_out += len(data)
                    writer.write(pack_frame(DATA, request_id, encode_meta_data(result, data)))
                elif msg_type == LIST:
                    writer.write(pack_frame(OK, request_id, json.dumps(self.pool.listing()).encode()))
                elif msg_type == STATS:
                    stats = self.pool.stats()
                    stats.update({
                        "uptime_seconds": max(0, time.time() - self.started_at),
                        "bytes_in": self.bytes_in,
                        "bytes_out": self.bytes_out,
                        "requests": self.requests,
                    })
                    writer.write(pack_frame(OK, request_id, json.dumps(stats).encode()))
                elif msg_type == PING:
                    writer.write(pack_frame(PONG, request_id, b""))
                else:
                    writer.write(pack_frame(ERROR, request_id, b"unsupported message type"))
                await writer.drain()
        except asyncio.IncompleteReadError:
            pass  # peer disconnected cleanly or mid-frame
        except (ConnectionError, BrokenPipeError):
            pass
        except (ProtocolError, ValueError, KeyError, CapacityError, TypeError) as exc:
            try:
                writer.write(pack_frame(ERROR, current_request_id, str(exc).encode("utf-8")[:2048]))
                await writer.drain()
            except (ConnectionError, OSError):
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass


async def open_client(host: str, port: int, token: str, ca_file: Optional[str] = None,
                      server_name: Optional[str] = None):
    ctx = None
    if ca_file:
        ctx = ssl.create_default_context(cafile=ca_file)
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port, ssl=ctx, server_hostname=(server_name or host) if ctx else None),
        timeout=5.0,
    )
    writer.write(pack_frame(AUTH, 1, token.encode()))
    await writer.drain()
    msg_type, request_id, payload = await asyncio.wait_for(read_frame(reader), timeout=5.0)
    if msg_type != AUTH_OK or request_id != 1:
        writer.close()
        await writer.wait_closed()
        raise PermissionError(payload.decode("utf-8", "replace"))
    return reader, writer


async def request(host: str, port: int, token: str, msg_type: int, payload: bytes = b"",
                  ca_file: Optional[str] = None, server_name: Optional[str] = None):
    reader, writer = await open_client(host, port, token, ca_file, server_name)
    try:
        writer.write(pack_frame(msg_type, 2, payload))
        await writer.drain()
        response_type, response_id, response = await asyncio.wait_for(read_frame(reader), timeout=10.0)
        if response_id != 2:
            raise ProtocolError("response request ID mismatch")
        if response_type == ERROR:
            raise RuntimeError(response.decode("utf-8", "replace"))
        return response_type, response
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass


def build_parser():
    parser = argparse.ArgumentParser(description="RAMLink symmetric bounded-object mesh MVP")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="serve this node's explicitly allocated RAM pool")
    serve.add_argument("--bind", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=18080)
    serve.add_argument("--capacity-mb", type=int, default=256)
    serve.add_argument("--token-file", required=True)
    serve.add_argument("--cert")
    serve.add_argument("--key")

    for name in ("put", "get", "list", "stats", "ping"):
        cmd = sub.add_parser(name)
        cmd.add_argument("host")
        cmd.add_argument("--port", type=int, default=18080)
        cmd.add_argument("--token-file", required=True)
        cmd.add_argument("--ca")
        cmd.add_argument("--server-name")

    put = sub.choices["put"]
    put.add_argument("key")
    put.add_argument("file")
    get = sub.choices["get"]
    get.add_argument("key")
    get.add_argument("output")
    return parser


def read_token(path: str) -> str:
    token = Path(path).read_text(encoding="utf-8").strip()
    if len(token) < 16:
        raise ValueError("token file must contain at least 16 characters")
    return token


async def run(args):
    token = read_token(args.token_file)
    if args.command == "serve":
        if not (0 < args.port < 65536):
            raise ValueError("invalid port")
        if args.bind not in ("127.0.0.1", "::1", "localhost") and not (args.cert and args.key):
            raise ValueError("non-loopback bind requires --cert and --key (TLS)")
        tls_context = None
        if args.cert or args.key:
            if not (args.cert and args.key):
                raise ValueError("both --cert and --key are required")
            tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            tls_context.minimum_version = ssl.TLSVersion.TLSv1_2
            tls_context.load_cert_chain(args.cert, args.key)
        server_obj = MeshServer(token, args.capacity_mb * 1024 * 1024)
        server = await asyncio.start_server(server_obj.handle, args.bind, args.port, ssl=tls_context)
        sockets = ", ".join(str(s.getsockname()) for s in (server.sockets or []))
        print(f"RAMLink mesh node listening on {sockets}; capacity={args.capacity_mb} MiB")
        async with server:
            await server.serve_forever()
        return

    ca = args.ca
    if args.command == "put":
        data = Path(args.file).read_bytes()
        if len(data) > MAX_FRAME - 4096:
            raise ValueError("file too large for MVP frame limit (about 1 MiB)")
        payload = encode_meta_data({"key": validate_key(args.key)}, data)
        _, response = await request(args.host, args.port, token, PUT, payload, ca, args.server_name)
        print(response.decode())
    elif args.command == "get":
        _, response = await request(args.host, args.port, token, GET,
                                    json.dumps({"key": validate_key(args.key)}).encode(), ca, args.server_name)
        meta, data = decode_meta_data(response)
        if hashlib.sha256(data).hexdigest() != meta.get("sha256"):
            raise ProtocolError("download hash verification failed")
        Path(args.output).write_bytes(data)
        print(json.dumps({"saved": args.output, "size": len(data), "sha256": meta["sha256"]}))
    elif args.command == "list":
        _, response = await request(args.host, args.port, token, LIST, b"{}", ca, args.server_name)
        print(json.dumps(json.loads(response), indent=2))
    elif args.command == "stats":
        _, response = await request(args.host, args.port, token, STATS, b"{}", ca, args.server_name)
        print(json.dumps(json.loads(response), indent=2))
    elif args.command == "ping":
        _, _ = await request(args.host, args.port, token, PING, b"", ca, args.server_name)
        print("pong")


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except (OSError, RuntimeError, ValueError, PermissionError, asyncio.TimeoutError,
            asyncio.IncompleteReadError, ProtocolError) as exc:
        print(f"ramlink: {exc}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
