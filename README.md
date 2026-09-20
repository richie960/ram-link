# RAM-Link

Experimental Android RAM-over-USB prototype.

Current transport: Android Termux RAM buffer -> TCP :8081 -> USB tethering -> Windows client.

The current milestone includes a 512-byte-sector block-device API in user space. It is not yet a native Windows RAM device or physical RAM expansion system.

## Quick start

Android / Termux:

    python server.py 512

Find the USB-tethering IP with `ip addr`, then set HOST in the Windows clients.

Windows:

    python clients/windows/ramlink_client.py
    python clients/windows/block_device_test.py

The block-device test performs sector reads, writes and SHA-256 integrity checks.

## Roadmap

- Android RAM buffer
- RML1 protocol
- USB tethering transport
- 512-byte block layer
- Windows virtual-device adapter
- Dokan integration
- Linux FUSE/NBD adapter
- macOS adapter
- Reconnection and security

Do not use this experimental volatile buffer for important data.

License: MIT
