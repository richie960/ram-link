#!/usr/bin/env python3
import socket, struct, hashlib, time

HOST="192.168.42.129"
PORT=8081
MAGIC=b"RML1"
HEADER=struct.Struct("!4sBQI")
OP_BLOCK_INFO,OP_BLOCK_READ,OP_BLOCK_WRITE=5,6,7
SECTOR_SIZE=512
MAX_BLOCK=1024*1024

def recv_all(s,n):
    b=bytearray()
    while len(b)<n:
        x=s.recv(min(MAX_BLOCK,n-len(b)))
        if not x: raise ConnectionError("RAM-Link server disconnected")
        b.extend(x)
    return bytes(b)

class RAMLinkBlockDevice:
    def __init__(self):
        self.s=socket.socket(); self.s.settimeout(15); self.s.connect((HOST,PORT))
        _,_,data=self.request(OP_BLOCK_INFO)
        self.sector_size,self.sector_count=struct.unpack("!QQ",data)
        print("Sector size:",self.sector_size)
        print("Sector count:",self.sector_count)
        print("Device size:",self.sector_size*self.sector_count,"bytes")

    def request(self,op,offset=0,length=0,payload=b""):
        self.s.sendall(HEADER.pack(MAGIC,op,offset,length))
        if payload: self.s.sendall(payload)
        h=recv_all(self.s,HEADER.size)
        magic,rop,roff,rlen=HEADER.unpack(h)
        if magic!=MAGIC: raise ValueError("Invalid response")
        return rop,roff,recv_all(self.s,rlen) if rlen else b""

    def read(self,sector,count):
        out=bytearray(); per=MAX_BLOCK//self.sector_size
        while count:
            n=min(count,per); out.extend(self.request(OP_BLOCK_READ,sector,n)[2])
            sector+=n; count-=n
        return bytes(out)

    def write(self,sector,data):
        if len(data)%self.sector_size: raise ValueError("Unaligned write")
        count=len(data)//self.sector_size; per=MAX_BLOCK//self.sector_size; p=0
        while count:
            n=min(count,per); size=n*self.sector_size
            self.request(OP_BLOCK_WRITE,sector,n,data[p:p+size])
            sector+=n; p+=size; count-=n

def main():
    d=RAMLinkBlockDevice()
    try:
        print("\nTEST 1: Read sector 0")
        print(d.read(0,1).hex())
        print("\nTEST 2: Write/read sector 100")
        block=bytearray(SECTOR_SIZE); msg=b"RAM-LINK BLOCK DEVICE TEST"; block[:len(msg)]=msg
        d.write(100,bytes(block)); returned=d.read(100,1)
        print("BLOCK TEST:","PASS" if returned==bytes(block) else "FAIL")
        print("\nTEST 3: Multi-sector integrity")
        count=2048; pattern=bytes(i%256 for i in range(count*SECTOR_SIZE))
        t=time.perf_counter(); d.write(1000,pattern); wt=time.perf_counter()-t
        t=time.perf_counter(); returned=d.read(1000,count); rt=time.perf_counter()-t
        a=hashlib.sha256(pattern).hexdigest(); b=hashlib.sha256(returned).hexdigest()
        print("Size:",len(pattern)/1024/1024,"MB")
        print("Write:",f"{wt:.3f} s"); print("Read:",f"{rt:.3f} s")
        print("Expected:",a); print("Returned:",b)
        print("MULTI-SECTOR TEST:","PASS" if a==b else "FAIL")
    finally: d.s.close()

if __name__=="__main__": main()
