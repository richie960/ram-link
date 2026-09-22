# RAM-Link Application Memory API

This is the first software-facing interface above the RAM-Link transport.

An application uses a normal memory-region object:

```python
from ramlink_memory_api import RAMLinkMemory

memory = RAMLinkMemory(remote_mb=256, cache_mb=32)
region = memory.allocate(16 * 1024 * 1024)

region.write(0, b"hello RAM-Link")
data = region.read(0, 14)

memory.flush()
region.close()
memory.close()
```

The application does not need to know about:

- RML1 packet framing
- Android
- TCP port 18080
- USB tethering
- leases
- the continuous Windows memory service

## Test it now

Start the Android server:

```bash
python server.py 512
```

Then on Windows start the continuous memory service:

```bat
python clients/windows/ramlink_memory_service.py PHONE_IP --mb 256
```

In a second Windows terminal:

```bat
python clients/windows/ramlink_memory_api.py --remote-mb 256 --cache-mb 32 --test-mb 8
```

Expected final line:

```
APPLICATION MEMORY API: PASS
```

This test proves that an application-facing API can allocate a RAM-Link memory region, write to it, flush it through the cache to Android RAM, read it back, and verify the result.

It does **not** claim that Windows has gained physical RAM. The next research stage is deeper OS memory integration, while the same core API can later receive Linux and macOS adapters.
