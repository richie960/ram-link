# Active remote-memory cache

This is the next RAM-Link layer after the continuous Windows memory service.

It implements a fixed-size page cache with LRU eviction:

Windows application/cache API
-> local RAM-Link cache
-> localhost:19080
-> continuous remote-memory service
-> USB/TCP :18080
-> Android RAM

The cache keeps frequently accessed pages locally and uses the phone-backed
memory as a larger remote backing region.

## Important

This is not yet Windows kernel virtual memory. It is an application-level
active memory/cache layer. The purpose is to prove the useful behavior before
attempting a Windows-native memory or storage integration.

## Test

Start Android:

```bash
python server.py 512
```

Start the continuous Windows service:

```bat
python ramlink_memory_service.py PHONE_IP --mb 256
```

Then run:

```bat
python ramlink_cache_manager.py --remote-mb 256 --cache-mb 32 --test-mb 64
```

The test writes data through the cache, flushes it to Android RAM, reads it
back through the cache, and verifies SHA-256.
