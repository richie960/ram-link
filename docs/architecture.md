# Architecture

Android Termux runs the RAM-Link server and allocates a bytearray. TCP port 8081 is reached from Windows through USB tethering.

    Windows -> block layer -> RML1/TCP -> USB tethering -> Termux -> Android RAM

ADB forwarding was used for the first proof of concept, but the current transport does not depend on ADB.

The host does not receive a physical Android RAM address. Operations are serialized over the protocol, so USB/network latency is much higher than local RAM latency.

Future work: Windows virtual device/Dokan adapter, Linux FUSE/NBD, macOS adapter, reconnection, authentication and benchmarking.
