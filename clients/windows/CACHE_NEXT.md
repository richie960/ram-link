# Placeholder: cache benchmark is included in ramlink_cache_manager.py

Run:

```bat
python ramlink_cache_manager.py --remote-mb 256 --cache-mb 32 --test-mb 64
```

The next milestone is to connect this cache to a Windows-facing virtual
filesystem/block adapter so ordinary workloads can use the same cache path.
