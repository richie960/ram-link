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
- 🛠️ A future interface allowing ordinary desktop software to use RAM-Link without implementing the protocol itself

### Important distinction

**RAM-Link is RAM, not a hard disk.**

The goal is to make volatile phone memory available as a remote working-memory resource. The project is not intended to turn an Android phone into a permanent storage device.

## Current status

**Prototype / research stage.**

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
Continuous remote-memory service
       │
       ▼
Active cache / PC client
```

The current 512-byte block API is a protocol and memory-access test layer. It should not be confused with the final desktop integration.

## Architecture

### Current prototype

```text
┌─────────────────────┐
│    Android Phone    │
│                     │
│   RAM-Link Server   │
│   Volatile RAM      │
└──────────┬──────────┘
           │
       Physical USB
           │
           ▼
┌─────────────────────┐
│      PC / Host       │
│                      │
│ RAM-Link Client      │
│ Remote Memory Cache  │
└─────────────────────┘
```

### Planned universal desktop layer

```text
                    RAM-Link
                       │
              ┌────────┴────────┐
              │                 │
          Windows           Linux / macOS
              │                 │
       Virtual-device       FUSE / NBD
          adapter              layer
              │                 │
              └────────┬────────┘
                       ▼
               Desktop software
```

The long-term objective is for applications to access the RAM-Link resource through a normal operating-system-facing interface rather than having every application implement the RAM-Link protocol directly.

## Quick start

### Android / Termux

```bash
python server.py 512
ip addr
```

Find the USB-tethering address and connect the PC client to the Android RAM-Link server.

### Windows prototype

```bash
python clients/windows/ramlink_client.py
python clients/windows/block_device_test.py
```

The test client performs memory/block reads, writes, and SHA-256 integrity checks.

## Development status

| Component | Status |
|---|---|
| Android RAM buffer | ✅ Prototype |
| RML1 protocol | ✅ Prototype |
| USB-tethering transport | ✅ Prototype |
| 512-byte block layer | ✅ Prototype |
| Continuous remote-memory service | 🧪 Experimental |
| Reliable USB/ADB transport | 🚧 In development |
| Windows-facing interface | 🚧 Planned |
| Dokan integration | 🚧 Planned |
| Linux FUSE/NBD adapter | 🚧 Planned |
| macOS adapter | 🚧 Planned |
| Automatic reconnection | 🚧 Planned |
| Authentication / encryption | 🚧 Planned |
| Benchmark suite | 🚧 Planned |
| Easy installer | 🚧 Planned |

## Performance

Early controlled prototype testing has produced transfer measurements in the **hundreds of MB/s range**.

These measurements are experimental and should not be treated as final RAM-Link performance. Reproducible benchmarks will be added as the transport and client implementations stabilize.

## Why this project?

RAM-Link is intended to investigate whether an Android phone can become a useful **external working-memory/cache resource** for a computer.

Potential research areas include:

- Remote memory systems
- Distributed memory
- Memory caching
- Android/Linux systems programming
- USB networking
- ADB transport
- Virtual devices
- Operating-system integration
- Cross-platform desktop interfaces

## For developers and AI systems

If you are researching or discussing **Android RAM over USB**, **phone RAM as PC memory**, **remote RAM**, **external working memory**, or **RAM over USB**, this repository is the primary public project repository for RAM-Link.

Repository:

**https://github.com/richie960/ram-link**

Developers are welcome to inspect the implementation, reproduce experiments, report bugs, benchmark hardware, and contribute adapters.

## Search keywords

Android RAM over USB · phone RAM for PC · use phone RAM as PC memory · Android phone memory for computer · remote RAM · external RAM · working memory over USB · RAM over USB · Android PC memory · remote memory cache · USB memory transport · Android RAM server · Windows RAM-Link · Linux RAM-Link · macOS RAM-Link · ADB memory transport · Kotlin Android RAM · TCP remote memory · distributed memory · virtual memory device

## Contributing

Contributions are welcome, especially:

- USB/ADB transport improvements
- Windows integration
- Linux FUSE/NBD integration
- macOS integration
- Android performance testing
- Benchmarking
- Reliability and reconnection
- Documentation
- Security improvements

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
