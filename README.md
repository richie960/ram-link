# RAM-Link

RAM-Link is an experimental remote-memory system using the RML1 protocol.

## Current capabilities

- Android RAM can be provided to a PC.
- PC RAM can now be provided to an Android/Termux client.
- Leases, keepalive, release, bounded transfers and integrity tests are supported.
- TCP 18080 can run over USB tethering or a private LAN/Wi-Fi network.

## Security and memory safety

RAM-Link treats network peers and all incoming protocol fields as untrusted. The
design requirements for bounded allocations, explicit buffer lifetimes, lease
validation, peer isolation, race-safe cleanup, integrity checks, resource quotas,
and safe transport are documented in
[`docs/SECURITY_MEMORY_SAFETY.md`](docs/SECURITY_MEMORY_SAFETY.md).

That document describes required controls and tests; it does not claim that every
control has already been implemented or audited. Keep RAM-Link experimental until
the implementation and tests demonstrate the relevant guarantees.

## PC provides RAM to Android

Windows:

    python clients/windows/ramlink_memory_provider.py 512

Android:

    python android/termux/client.py <PC_IP> 256

This is a transport/protocol proof of concept. The next layer is integrating the
Android borrower with a memory/cache subsystem so selected pages can be moved to
the remote provider without pretending the remote bytes are local physical RAM.
