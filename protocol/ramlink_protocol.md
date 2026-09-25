# RAM-Link RML1 Protocol

RAM-Link now supports both resource directions over the same protocol.

## Directions

- Android provider -> PC borrower
- PC provider -> Android borrower

The provider owns a volatile RAM buffer and grants non-overlapping leased regions.
The borrower accesses that region with READ/WRITE while the lease is alive.

## Transport

TCP port 18080. USB tethering/private LAN/Wi-Fi can carry the TCP connection.

## Operations

1 INFO
2 READ
3 WRITE
4 PING
5 BLOCK_INFO
6 BLOCK_READ
7 BLOCK_WRITE
8 BORROW
9 RELEASE
10 KEEPALIVE

## PC -> Android test

Windows:

    python clients/windows/ramlink_memory_provider.py 512

Android/Termux:

    python android/termux/client.py <PC_IP> 256

The test performs BORROW -> WRITE -> READ -> VERIFY -> KEEPALIVE -> RELEASE.

This validates bidirectional remote-memory transport. It does not yet make the Android
kernel treat the remote region as ordinary physical application RAM. That requires a
separate Android memory/cache integration layer.
