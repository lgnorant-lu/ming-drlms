# Legacy Tests (Phase 15 / Ed25519)

> **Status**: Archived — NOT run in CI  
> **Last Review**: 2025-12-10  

These test files are archived from the Phase 15 implementation when
`IdentityManager` used standalone Ed25519 keys stored in `identity.json`.

## Phase 15.5 Migration Summary

| Aspect | Phase 15 (Legacy) | Phase 15.5+ (Current) |
|--------|------------------|----------------------|
| Identity Storage | `identity.json` | `e2ee_keys.json` (LocalKeyStore) |
| Signing Algorithm | Ed25519 | XEdDSA (X25519 + EdDSA) |
| Key Generation | `Ed25519PrivateKey.generate()` | `generate_device_keys()` |
| Manager Class | Standalone `IdentityManager` | Unified `IdentityManager` → `LocalKeyStore` |

## Archived Files

| File | Original Purpose | Why Archived |
|------|------------------|--------------|
| `test_identity_manager.py` | Old `IdentityManager` tests | Ed25519/identity.json removed |
| `test_phase15_integration.py` | `create_identity()` API tests | API deprecated |
| `test_dumb_relay.py` | Relay signer tests | Old IdentityManager |
| `test_event_hash.py` | Ed25519 signing functions | Replaced by XEdDSA |
| `test_relay_sync_verify.py` | Relay signature verify | Uses Ed25519 |
| `test_xeddsa_bridge.py` | XEdDSA bridge tests | Moved to main tests |

## Current Implementation

For Phase 15.5+ XEdDSA-based implementation, see:

```
tests/python/
├── test_xeddsa_e2e.py          # XEdDSA end-to-end tests
├── test_mp2_identity_strict.py  # MP2 login with XEdDSA
├── test_phase16_integration.py  # Phase 16 multi-relay tests
└── test_relay_*.py             # Phase 16 relay module tests

src/ming_drlms/core/
├── identity_manager.py         # Unified identity (Phase 15.5)
├── relay_signer.py             # XEdDSA Relay signing
└── pysignal/                   # Signal Protocol bindings
```

## Decision

**Keep as archive** — These tests document historical implementation and may
be useful for understanding migration decisions. No active maintenance needed.
