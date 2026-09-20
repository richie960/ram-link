# Block Device Layer

The current Windows layer exposes 512-byte sectors with aligned reads and writes, multi-sector transfers and SHA-256 integrity testing.

It is a user-space Python test layer, not a mounted Windows drive. Keeping it separate from the future virtual-device adapter allows the protocol to be validated first.
