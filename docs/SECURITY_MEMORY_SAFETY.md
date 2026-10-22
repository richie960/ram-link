# RAM-Link Security and Memory-Safety Design

**Status:** design requirements for the experimental proof of concept. This document is not a claim that every control is already implemented or independently audited.

## Scope and threat model

RAM-Link moves bounded data over a network between independently managed devices. Treat every peer, packet, length field, object identifier, lease token, and payload as untrusted—even on USB tethering or a private LAN. A peer may be buggy, compromised, disconnected, replay messages, send malformed frames, or try to consume excessive memory or CPU.

RAM-Link is an experimental transport/protocol proof of concept, not transparent physical RAM and not yet a production-secure memory service. Remote bytes must remain explicitly managed application data; do not expose them as arbitrary process pointers or assume remote memory has local-memory semantics.

## Required invariants

1. **No remote pointers.** Never transmit, deserialize, persist, or trust a raw process pointer or native address from a peer. Use protocol-defined IDs and bounded offsets within a validated object.
2. **Explicit ownership and lifetime.** Every buffer/object has one documented owner and lifecycle. A buffer must not be read after release, reused while an operation can still access it, or returned to a pool before all readers/writers have finished.
3. **Lease-scoped access.** Every object operation must validate the authenticated peer/session, object ID, lease state, permissions, and expiry. A released, expired, or unknown lease must fail closed.
4. **Per-peer isolation.** Enforce authorization and quotas per peer and per session. Never let a peer select another peer's object by guessing IDs. Do not treat unguessable IDs alone as authorization.
5. **Bounded framing.** Validate frame type, declared length, integer conversions, maximum frame/object size, and remaining bytes before allocating or copying. Reject truncated, oversized, malformed, or trailing-invalid frames safely.
6. **Integrity and completeness.** Verify expected lengths and integrity checks before making received data available. Do not expose partially received or unverified objects as complete.
7. **Concurrency safety.** Serialize lifecycle transitions or use locks/reference counts so release, timeout, disconnect, and concurrent reads/writes cannot race into use-after-release or double-release.
8. **Fail closed on errors.** On malformed input, checksum failure, timeout, or state inconsistency, reject the operation and release only resources owned by that operation. Never recover by using stale state.
9. **Resource budgets.** Set configurable hard caps for active peers, outstanding requests, object size, total pool/cache bytes, queued bytes, and request duration. Apply backpressure and per-peer quotas; do not allocate solely from peer-declared sizes.
10. **Safe cleanup.** Disconnect, lease expiry, cancellation, and exceptions must converge on idempotent cleanup. Invalidate handles before storage can be reused, and ensure outstanding tasks cannot retain access to released storage.
11. **No executable payloads.** Treat remote content as bytes only. Never deserialize untrusted data using unsafe object deserialization, dynamically execute received content, or load code from a peer.
12. **Transport security.** Before use beyond a trusted development network, add authenticated peer identity and encrypted transport with proper certificate/key verification. Do not rely on a private IP, SSID, or USB connection as authentication.
13. **Secrets and logs.** Never log credentials, private keys, session secrets, or full memory payloads. Keep diagnostic logs bounded and avoid leaking one peer's data to another.
14. **Safe defaults.** Bind listeners to loopback by default for development. Exposing a listener to LAN/internet must require an explicit configuration choice and clear warning.

## Buffer/object lifecycle

Use a state machine similar to:

`NEW -> ALLOCATED -> ACTIVE -> RELEASING -> RELEASED`

A failed or cancelled operation must transition to cleanup without reviving an old handle. A released object ID must not become valid for a later object accidentally; use generation/version values or fresh unpredictable identifiers where appropriate. Check state and ownership at the point of each operation, not only when a connection is established.

A safe receive path should:

1. Read a fixed-size header with a strict timeout.
2. Validate protocol version, message type, declared length, and limits before allocating.
3. Read exactly the permitted number of bytes into an operation-owned bounded buffer.
4. Verify object/lease authorization, expected length, and integrity.
5. Publish the object atomically only after the complete payload passes validation.
6. Release temporary buffers on every exception, cancellation, timeout, and disconnect path.

## Testing requirements

Add tests before treating these controls as implemented:

- Zero-length, negative-equivalent, overflow-sized, oversized, truncated, and malformed frames.
- Unknown message types, invalid IDs, expired/released leases, wrong-peer access, and replayed operations.
- Concurrent read/write/release, disconnect during transfer, timeout during transfer, and repeated cleanup.
- Checksum mismatch and incomplete payloads never becoming visible as valid objects.
- Many peers/requests and repeated failed requests stay within memory, queue, and CPU limits.
- Reconnection cannot revive stale sessions or access previously released objects.
- Fuzz protocol parsing and state transitions; run tests on supported platforms.
- Confirm logs and error responses do not disclose payload data or secrets.

A test passing is evidence for that test only; it is not a security audit. Track unimplemented requirements as open work rather than claiming complete protection.

## Development checklist

- [ ] Document protocol maximums and enforce them at every receive/allocation boundary.
- [ ] Use operation-owned buffers and explicit object/lease state transitions.
- [ ] Enforce per-peer authorization and quotas on every operation.
- [ ] Make release, timeout, cancellation, and disconnect cleanup idempotent and race-safe.
- [ ] Add malformed-input, lifecycle-race, isolation, resource-exhaustion, and fuzz tests.
- [ ] Authenticate peers and encrypt transport before untrusted-network deployment.
- [ ] Review dependencies and run static analysis/security tests before releases.

## Related vulnerability lessons

Memory-safety incidents in other software are useful reminders to review resource lifetime, error recovery, and stale state. They do not by themselves prove RAM-Link has the same bug or that a particular design change prevents every vulnerability. Evaluate RAM-Link against its own code, protocol, tests, and threat model.

Report suspected security issues privately to the repository maintainer rather than publishing working exploit details before a fix is available.
