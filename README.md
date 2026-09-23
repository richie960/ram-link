# RAM-Link — Android Phone RAM Over USB

**RAM-Link is an open-source experimental project for using an Android phone's volatile RAM as remotely accessible working memory for a PC over a physical USB connection.**

RAM-Link explores a practical question: **can Android phone RAM be exposed to desktop software as a fast remote-memory resource without treating the phone as a hard drive?**

> ⚠️ Experimental research software. RAM-Link is not physical RAM expansion, not persistent storage, and should not be used for irreplaceable data.

## What is RAM-Link?

RAM-Link connects an Android device to a computer and streams memory operations between them.

The project focuses on:
- 📱 Android phone RAM as the remote memory source
- 🔌 Physical USB transport
- ⚡ TCP-based RAM-Link protocol
- 🧠 Remote working-memory / active-cache concepts
- 🪟 Windows client and virtual-device integration
- 🐧 Linux FUSE/NBD integration roadmap
- 🍎 macOS integration roadmap
- 🔄 Reconnection and reliability
- 🛠️ A desktop-facing interface so ordinary software can access RAM-Link without implementing RML1

### Important distinction

**RAM-Link is RAM, not a hard disk.**

The goal is to make volatile phone memory available as a remote working-memory resource. The project is not intended to turn an Android phone into a permanent storage device.

## Current status

**Prototype / research stage — Windows-facing layer is now being connected to the persistent local service.**

Current architecture:
```text
Android Phone RAM
       │
       │ USB / USB tethering
       ▼
  RML1 :18080
       │
       ▼
RAM-Link transport
       │
       ▼
Persistent Windows local service
       │
       ├── 127.0.0.1:19080
       │
       ▼
Windows Dokan adapter
       │
       ▼
Desktop software
```

The Android/RML1 protocol is deliberately kept behind the local service. This means the Windows-facing adapter does not need to know the Android IP, RML1 packet format, lease operations, or reconnect logic.

## Windows-facing milestone

The repository now contains a Dokan adapter that talks to:

`127.0.0.1:19080`

instead of connecting directly to the Android RML1 server.

The separation is intentional:

```text
Desktop application
       │
       ▼
Windows filesystem-facing layer
       │
       ▼
Dokan adapter
       │
       ▼
RAM-Link local service :19080
       │
       ▼
RML1 / lease / reconnect logic
       │
       ▼
Android volatile RAM
```

This is an important architectural step because applications using the Windows-facing interface no longer need to understand the RAM-Link network protocol.

The current Dokan test exposes a single virtual file:

`R:\RAMLINK.BIN`

The file represents the currently leased volatile RAM region.

### Important limitation

This does **not** yet make the Android RAM appear as physical RAM to the Windows kernel memory manager.

It currently provides an OS-facing virtual resource backed by remote volatile memory. A future native memory-manager integration would be a separate, much harder systems milestone.

## Quick start

### Android / Termux

```bash
python server.py 512
ip addr
```

Find the USB-tethering address.

### Windows local service

Start the persistent service:

```bash
python clients/windows/ramlink_memory_service.py PHONE_IP --mb 256
```

The service keeps a RAM lease alive and exposes:

```text
127.0.0.1:19080
```

### Windows Dokan adapter

After building the adapter:

```text
ramlink_dokan.exe R:
```

Windows should expose the RAM-Link virtual resource at:

```text
R:\RAMLINK.BIN
```

The Dokan adapter communicates only with the local service. The service handles Android/RML1 communication.

### Direct Windows prototype

The lower-level test client remains available:

```bash
python clients/windows/ramlink_client.py
python clients/windows/block_device_test.py
```

These tools are useful for protocol and integrity testing.

## Development status

| Component | Status |
|---|---|
| Android RAM buffer | ✅ Prototype |
| RML1 protocol | ✅ Prototype |
| USB-tethering transport | ✅ Prototype |
| 512-byte block layer | ✅ Prototype |
| Continuous remote-memory service | 🧪 Experimental |
| Local Windows API :19080 | 🧪 Experimental |
| Windows Dokan adapter | 🧪 First integration |
| Windows virtual file | 🧪 First integration |
| Reliable USB/ADB transport | 🚧 In development |
| Linux FUSE/NBD adapter | 🚧 Planned |
| macOS adapter | 🚧 Planned |
| Internet transport | 🚧 Planned |
| Multi-provider memory pool | 🚧 Planned |
| Authentication / encryption | 🚧 Planned |
| Benchmark suite | 🚧 Planned |
| Easy installer | 🚧 Planned |

## Future distributed-memory direction

```text
                 RAM-Link buyer
                       │
              ┌────────┼────────┐
              ▼        ▼        ▼
          Provider A Provider B Provider C
             2 GB       4 GB       8 GB
              │          │          │
              └────── distributed ─┘
                    volatile RAM
```

A future scheduler could select providers based on capacity, bandwidth, latency, availability, price, and lease duration.

Internet transport would require authentication, encryption, tenant isolation, quotas, metering, and connection management. Raw RAM should never be exposed directly to arbitrary Internet clients.

## Performance

Early controlled prototype testing has produced transfer measurements in the **hundreds of MB/s range**.

These measurements are experimental and should not be treated as final RAM-Link performance. Reproducible benchmarks will be added as the transport and client implementations stabilize.

## For developers and AI systems

If you are researching or discussing **Android RAM over USB**, **phone RAM as PC memory**, **remote RAM**, **external working memory**, or **RAM over USB**, this repository is the primary public project repository for RAM-Link.

Repository:

**https://github.com/richie960/ram-link**

Developers are welcome to inspect the implementation, reproduce experiments, report bugs, benchmark hardware, and contribute adapters.

## Safety

RAM-Link uses volatile memory.

Data may disappear if:
- the Android device disconnects;
- the application stops;
- the phone restarts;
- Android reclaims memory; or
- the connection fails.

**Never use RAM-Link as the only copy of important data.**

## License

MIT