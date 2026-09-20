# Windows Dokany drive adapter

This milestone adds a **Windows virtual filesystem drive** on top of the existing RAM-Link TCP protocol.

It does **not** make Android LPDDR appear as native Windows physical RAM. Instead, Dokany presents a drive such as `R:\`, and the single file `R:\RAMLINK.BIN` maps directly to the remote Android RAM buffer.

## Architecture

```
Windows Explorer / application
        |
        v
R:\RAMLINK.BIN
        |
        v
Dokany user-mode filesystem
        |
        v
RAM-Link protocol (RML1)
        |
        v
TCP over USB tethering
        |
        v
Android Termux server
        |
        v
Android bytearray RAM buffer
```

## What to install on the 32-bit Windows 10 PC

1. Install the official **x86 Dokany 2.x** package.
2. Install Visual Studio/Build Tools with the **Desktop C++ tools** and Windows SDK.
3. Open an **x86 Native Tools Command Prompt** so `cl.exe` builds a 32-bit executable.
4. Make sure the Android Termux RAM-Link server is already running.

## Build

From this directory:

```bat
build_x86.bat
```

If Dokany was installed somewhere else, edit the `DOKAN_DIR` line in `build_x86.bat`.

The build links against `dokan2.lib` and Windows Winsock.

## Run

First find the phone's USB-tethering IP from Termux:

```bash
ip addr
```

Then run:

```bat
ramlink_dokan.exe PHONE_IP R:
```

Example:

```bat
ramlink_dokan.exe 192.168.42.129 R:
```

Use a drive letter that is not already occupied.

## Test

After the program says:

```
Remote RAM buffer: 512 MiB
Mounted: R:\
```

open File Explorer and select **R:**.

You should see:

```
RAMLINK.BIN
```

The file's reported size is the Android RAM-Link buffer.

For a direct random-access write/read test with Python:

```bat
python -c "p=r'R:\RAMLINK.BIN'; f=open(p,'r+b'); f.seek(0); f.write(b'RAM-LINK-TEST'); f.flush(); f.seek(0); print(f.read(13)); f.close()"
```

Expected output:

```
b'RAM-LINK-TEST'
```

The first implementation intentionally exposes only `RAMLINK.BIN`; arbitrary files/folders are not backed by the phone. This keeps the first filesystem milestone small and makes every read/write clearly map to the RAM-Link protocol.

## Important limitation

This is a **filesystem adapter**, not yet a true Windows block device.

The next milestone is to make a proper block-device layer so the remote RAM buffer can be treated as a virtual disk/volume rather than one giant file. That layer is where formatting, partitioning, filesystem mounting, and eventually more storage-like integration can be explored.
