# RAM-Link

RAM-Link is an experimental remote-memory system using the RML1 protocol.

## Current capabilities

- Android RAM can be provided to a PC.
- PC RAM can now be provided to an Android/Termux client.
- Leases, keepalive, release, bounded transfers and integrity tests are supported.
- TCP 18080 can run over USB tethering or a private LAN/Wi-Fi network.

## PC provides RAM to Android

Windows:

    python clients/windows/ramlink_memory_provider.py 512

Android:

    python android/termux/client.py <PC_IP> 256

This is a transport/protocol proof of concept. The next layer is integrating the
Android borrower with a memory/cache subsystem so selected pages can be moved to
the remote provider without pretending the remote bytes are local physical RAM.
