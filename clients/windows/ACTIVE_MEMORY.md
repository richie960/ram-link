# Windows Active Remote Memory

The continuous-memory layer keeps an Android RAM lease alive and exposes it through a localhost API.

Architecture:
Windows software -> RAM-Link local API :19080 -> RML1 -> USB/TCP :18080 -> Android RAM

Start Android:
```bash
python server.py 512
```

Start Windows:
```bat
python ramlink_memory_service.py 192.168.x.x --mb 256
```

The service keeps the 256 MiB lease alive automatically.

Local API: TCP 127.0.0.1:19080

Commands: STATUS, PING, READ <offset> <length>, WRITE <offset> <length> followed by payload.

Important: this is remote memory, not additional physical Windows DDR RAM. The next layer can build a cache, virtual-memory-like backing store, or virtual filesystem/block adapter on this stable service.