# RAM-Link

**Use Android phone RAM as remotely accessible working memory for a PC or application.**

RAM-Link is an experimental open-source project exploring **Android RAM over a physical USB connection**. The project is designed around memory operations—not file sharing and not turning phone RAM into a hard drive.

> ⚠️ **Experimental:** RAM-Link is not physical RAM expansion and should not be used for important or irreplaceable data.

## Why RAM-Link?

What if an Android phone could provide part of its available memory to a computer over a physical USB connection?

RAM-Link explores that idea with:

- 📱 Android RAM buffer
- 🔌 USB-connected transport
- ⚡ TCP-based data streaming
- 🧠 Remote RAM / working-memory interface
- 🪟 Windows client
- 🐧 Linux FUSE/NBD roadmap
- 🍎 macOS adapter roadmap
- 🔄 Reconnection and reliability roadmap

## Current status

**Prototype / research stage**

Current implementation:

**Android RAM → RML1 :18080 → USB/tethering transport → continuous remote-memory service → active cache**

The 512-byte block API is a protocol test interface; the project direction is **RAM access, not storage**.

RAM-Link is currently a prototype—not a native Windows RAM device, not a replacement for physical RAM, and not yet a production-ready storage driver.

## Architecture

```text
┌──────────────────┐
│   Android Phone  │
│   RAM Buffer     │
│    RAM-Link      │
└────────┬─────────┘
         │ USB
         ▼
┌──────────────────┐
│   Windows / PC   │
│ RAM-Link Client  │
│ Block Device API │
└──────────────────┘
```

Future:

```text
Android RAM
    │
    │ USB / ADB
    ▼
RAM-Link Transport
    │
    ├── Windows → Dokan / virtual device
    ├── Linux   → FUSE / NBD
    └── macOS   → native adapter
```

## Quick start

### Android / Termux

```bash
python server.py 512
ip addr
```

Find the USB-tethering IP and start the Windows memory service with that address.

### Windows

```bash
python clients/windows/ramlink_client.py
python clients/windows/block_device_test.py
```

The block-device test performs sector reads, writes, and SHA-256 integrity checks.

## Performance experiments

RAM-Link is being tested over physical USB connections.

Early prototype testing has produced transfer measurements in the **hundreds of MB/s range in controlled tests**. Reproducible benchmark results will be documented as the implementation stabilizes.

## Demo

A short video demonstration will show the Android phone, USB connection, RAM-Link server, PC client, block reads/writes, integrity checks, and performance measurements.

## Roadmap

- [x] Android RAM buffer
- [x] RML1 protocol
- [x] USB-tethering transport
- [x] 512-byte block layer
- [ ] Reliable USB/ADB transport
- [ ] Windows virtual-device adapter
- [ ] Dokan integration
- [ ] Linux FUSE/NBD adapter
- [ ] macOS adapter
- [ ] Automatic reconnection
- [ ] Authentication and encryption
- [ ] Benchmark suite
- [ ] Installer / easy setup
- [ ] Public release

## Search keywords

**Android RAM over USB · phone RAM for PC · remote RAM · working memory · RAM over USB · Android PC memory · Windows memory interface · Linux memory interface · macOS memory interface · Kotlin · Android · TCP · ADB**

## Contributing

RAM-Link welcomes testing, benchmarking, bug reports, hardware compatibility reports, and implementation ideas.

## Safety

RAM-Link uses volatile memory. Data can disappear when the phone disconnects, the application stops, the phone restarts, or memory is reclaimed.

**Never use RAM-Link as the only copy of important data.**

## License

MIT
