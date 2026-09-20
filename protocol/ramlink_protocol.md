# RAM-Link RML1 Protocol

Header: 17 bytes, network order: `!4sBQI`.

- Magic: `RML1`
- Operation: 1 byte
- Offset/sector: 8 bytes
- Length/count: 4 bytes

Operations: INFO=1, READ=2, WRITE=3, PING=4, BLOCK_INFO=5, BLOCK_READ=6, BLOCK_WRITE=7.

Block operations use 512-byte sectors and a maximum transfer of 1 MiB.

The server validates all ranges before accessing the allocated RAM buffer.
