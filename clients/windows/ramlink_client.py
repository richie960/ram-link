#!/usr/bin/env python3
import socket, struct, hashlib, time

HOST = "192.168.42.129"
PORT = 8081
MAGIC=b"RML1"
HEADER=struct.Struct("!4sBQI")
OP_INFO,OP_READ,OP_WRITE,OP_PING=1,2,3,4
MAX_BLOCK=1024*1024

def recv_all(sock,size):
    data=bytearray()
    while len(data)<size:
        chunk=sock.recv(min(MAX_BLOCK,size-len(data)))
        if not chunk: raise ConnectionError("Server disconnected")
        data.extend(chunk)
    return bytes(data)

def request(sock,op,offset=0,data=b""):
    sock.sendall(HEADER.pack(MAGIC,op,offset,len(data)))
    if data: sock.sendall(data)
    h=recv_all(sock,HEADER.size)
    magic,rop,roff,rlen=HEADER.unpack(h)
    if magic!=MAGIC: raise ValueError("Invalid response")
    return rop,roff,recv_all(sock,rlen) if rlen else b""

def main():
    s=socket.socket(); s.settimeout(15)
    try: s.connect((HOST,PORT))
    except Exception as e: print("CONNECTION FAILED:",e); return
    try:
        while True:
            print("\n1 INFO\n2 PING\n3 WRITE\n4 READ\n5 INTEGRITY\n6 EXIT")
            c=input("Select: ").strip()
            if c=="1": print(request(s,OP_INFO)[2].decode(errors="replace"))
            elif c=="2":
                t=time.perf_counter(); print("PING:",request(s,OP_PING)[2].decode(), "%.3f ms"%((time.perf_counter()-t)*1000))
            elif c in ("3","4","5"):
                mb=int(input("MB [1]: ").strip() or "1"); size=mb*1024*1024
                pattern=(bytes(range(256))*((size//256)+1))[:size]
                if c in ("3","5"):
                    for o in range(0,size,MAX_BLOCK):
                        n=min(MAX_BLOCK,size-o); request(s,OP_WRITE,o,pattern[o:o+n])
                if c in ("4","5"):
                    out=bytearray()
                    for o in range(0,size,MAX_BLOCK): out.extend(request(s,OP_READ,o)[2])
                    if c=="5": print("INTEGRITY:", "PASS" if hashlib.sha256(out).digest()==hashlib.sha256(pattern).digest() else "FAIL")
            elif c=="6": break
    finally: s.close()

if __name__=="__main__": main()
