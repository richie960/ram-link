# RAMLink Symmetric Mesh MVP

This branch adds a portable asyncio mesh proof of concept. Every node can run a server (provider) and use the same CLI as a client (consumer). A provider exposes only explicitly uploaded, bounded byte objects; this is **not** transparent physical RAM, arbitrary process-memory sharing, or a production paging system.

## Safety and scope

- Python 3.10+; standard library only.
- 1 MiB maximum protocol frame in this MVP.
- Each node's pool is bounded by `--capacity-mb`.
- Loopback binding is the default.
- Non-loopback listeners require TLS certificate and key. Clients should verify TLS with `--ca`.
- Use a long random bearer token stored in a file with restrictive permissions.
- Do not expose this service to the public internet without additional identity, authorization, rate limits, replay protections, audit logs, and deployment hardening.
- Data lives in the provider process and disappears when it exits. Do not upload secrets or sensitive data.

## Quick start (local test)

Create a token file (keep it secret):

```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))' > token.txt
chmod 600 token.txt
```

Start a node in terminal 1:

```bash
python -m ramlink_mesh.agent serve --bind 127.0.0.1 --port 18080 --capacity-mb 64 --token-file token.txt
```

In terminal 2, create and upload a sample object:

```bash
printf 'RAMLink mesh test\n' > sample.bin
python -m ramlink_mesh.agent put 127.0.0.1 --port 18080 --token-file token.txt sample/demo sample.bin
python -m ramlink_mesh.agent list 127.0.0.1 --port 18080 --token-file token.txt
python -m ramlink_mesh.agent get 127.0.0.1 --port 18080 --token-file token.txt sample/demo restored.bin
python -m ramlink_mesh.agent stats 127.0.0.1 --port 18080 --token-file token.txt
cmp sample.bin restored.bin
```

## Live dashboard (new)

The dashboard is a local, read-only web page that polls the configured peers every five seconds. It shows online/offline status, configured RAMLink pool capacity, used/available bytes, object count, request count, uptime and transferred bytes.

1. Create a token as above, and start a local node in another Termux session if you want a real local peer.
2. Copy `config/dashboard.example.json` to `config/dashboard.json`.
3. Edit `config/dashboard.json`. For the local node, use host `127.0.0.1`, port `18080`, and token file `../token.txt`. Remove the laptop example until you have configured a trusted TLS certificate and matching CA file.
4. Start the dashboard from the repository root:

```bash
python -m ramlink_mesh.dashboard --config config/dashboard.json --port 8765
```

5. Open `http://127.0.0.1:8765` in the browser on the same device. On Android, Termux and the browser run on the same phone, so localhost is appropriate.
6. Stop the dashboard with Ctrl+C in the Termux session.

The dashboard itself intentionally binds only to loopback. You can monitor peers on a LAN or across the internet **only when each remote peer has a properly configured TLS endpoint and its CA/name configured in the dashboard JSON**. For viewing the dashboard from another device, use a trusted VPN or SSH tunnel; do not expose its HTTP port publicly. The dashboard never displays tokens.

The values labelled “pool” refer only to RAMLink's explicitly allocated object buffers, not total system RAM, and not guaranteed memory available to another process.

## Two-node test

Install/run this branch on two trusted machines. Configure the receiving node with a TLS certificate and key, bind to a private interface, and open the port only on the trusted LAN. On the client, provide the certificate authority with `--ca ca.pem` and the matching DNS name with `--server-name node.example`. Keep the same secret token on both sides. Do not omit `--ca` for untrusted networks; without a CA, the client does not verify server identity.

The same process can both serve and consume resources: run `serve` on each node and use `put/get/list/stats` against any peer. A future scheduler can register these endpoints and select peers automatically.

## Tests

```bash
python -m unittest discover -s tests -v
python -m ramlink_mesh.dashboard --help
```

## Next engineering steps

1. Add TLS client identity (mTLS) and per-node authorization.
2. Add chunk streaming above the single-frame MVP, bounded concurrency, and backpressure.
3. Add peer discovery/rendezvous and leases; never trust self-reported earnings alone.
4. Add a local LRU cache and immutable content-addressed objects.
5. Add GPU task execution as a separate sandboxed work queue.
6. Only then evaluate platform-specific storage or paging adapters. Network-backed bytes must not be represented as guaranteed local DRAM.
