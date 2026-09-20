#!/usr/bin/env python3
import socket, struct, threading, sys

HOST = "0.0.0.0"
PORT = 8081
MAGIC = b"RML1"
HEADER = struct.Struct("!4sBQI")
OP_INFO, OP_READ, OP_WRITE, OP_PING = 1, 2, 3, 4
OP_BLOCK_INFO, OP_BLOCK_READ, OP_BLOCK_WRITE = 5, 6, 7
SECTOR_SIZE = 512
MAX_BLOCK = 1024 * 1024

class RAMLinkServer:
    def __init__(self, size_mb):
        self.size = (size_mb * 1024 * 1024) // SECTOR_SIZE * SECTOR_SIZE
        print("RAM-LINK ANDROID SERVER - USB TETHERING MODE")
        try:
            self.memory = bytearray(self.size)
        except MemoryError:
            sys.exit("ERROR: Not enough Android RAM.")
        self.sectors = self.size // SECTOR_SIZE
        self.total_reads = self.total_writes = 0
        self.total_read_bytes = self.total_write_bytes = 0
        self.lock = threading.Lock()
        print("Buffer:", self.size, "bytes | Sectors:", self.sectors)

    def recv_all(self, conn, size):
        data = bytearray()
        while len(data) < size:
            chunk = conn.recv(min(MAX_BLOCK, size - len(data)))
            if not chunk: raise ConnectionError("Client disconnected")
            data.extend(chunk)
        return bytes(data)

    def send_header(self, conn, op, offset, length):
        conn.sendall(HEADER.pack(MAGIC, op, offset, length))

    def valid(self, offset, length):
        return offset >= 0 and length >= 0 and offset <= self.size and length <= self.size - offset

    def valid_blocks(self, sector, count):
        return sector >= 0 and count >= 0 and sector <= self.sectors and count <= self.sectors - sector

    def info(self, conn):
        data = ("RAM-LINK
version=2
protocol=RML1
transport=USB_TETHERING
"
                f"buffer_bytes={self.size}
buffer_mb={self.size/1024/1024:.2f}
"
                f"sector_size={SECTOR_SIZE}
sector_count={self.sectors}
max_block={MAX_BLOCK}
").encode()
        self.send_header(conn, OP_INFO, 0, len(data)); conn.sendall(data)

    def handle(self, conn, op, offset, length):
        if op == OP_INFO: return self.info(conn)
        if op == OP_PING:
            data=b"PONG"; self.send_header(conn, op, 0, len(data)); conn.sendall(data); return
        if op in (OP_READ, OP_WRITE):
            if length > MAX_BLOCK or not self.valid(offset, length): raise ValueError("Invalid byte range")
            if op == OP_WRITE:
                data=self.recv_all(conn,length)
                with self.lock: self.memory[offset:offset+length]=data
            else:
                with self.lock: data=bytes(self.memory[offset:offset+length])
                self.send_header(conn,op,offset,length); conn.sendall(data); return
            self.send_header(conn,op,offset,length); return
        if op == OP_BLOCK_INFO:
            data=struct.pack("!QQ",SECTOR_SIZE,self.sectors)
            self.send_header(conn,op,0,len(data)); conn.sendall(data); return
        if op in (OP_BLOCK_READ, OP_BLOCK_WRITE):
            if not self.valid_blocks(offset,length) or length*SECTOR_SIZE > MAX_BLOCK:
                raise ValueError("Invalid block range")
            byte_offset=offset*SECTOR_SIZE; byte_length=length*SECTOR_SIZE
            if op == OP_BLOCK_WRITE:
                data=self.recv_all(conn,byte_length)
                with self.lock: self.memory[byte_offset:byte_offset+byte_length]=data
                self.send_header(conn,op,offset,length)
            else:
                with self.lock: data=bytes(self.memory[byte_offset:byte_offset+byte_length])
                self.send_header(conn,op,offset,length); conn.sendall(data)
            return
        raise ValueError("Unknown operation")

    def client(self, conn, address):
        print("[+] Connected:", address)
        try:
            while True:
                header=self.recv_all(conn,HEADER.size)
                magic,op,offset,length=HEADER.unpack(header)
                if magic != MAGIC: raise ValueError("Invalid magic")
                self.handle(conn,op,offset,length)
        except Exception as e:
            print("[-] Client:", address, e)
        finally: conn.close()

    def start(self):
        s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        s.bind((HOST,PORT)); s.listen(5)
        print("SERVER READY - TCP port",PORT)
        try:
            while True:
                c,a=s.accept()
                threading.Thread(target=self.client,args=(c,a),daemon=True).start()
        except KeyboardInterrupt: pass
        finally: s.close()

if __name__ == "__main__":
    size_mb=int(sys.argv[1]) if len(sys.argv)>1 else 512
    if size_mb < 1: sys.exit("RAM size must be >= 1 MB")
    RAMLinkServer(size_mb).start()
