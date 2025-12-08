# Legacy Tests (Phase 15 / Ed25519)

These test files are archived from the Phase 15 implementation when
`IdentityManager` used standalone Ed25519 keys stored in `identity.json`.

**Phase 15.5 Migration**:
- Identity storage unified to `LocalKeyStore` (`e2ee_keys.json`)
- Ed25519 replaced by XEdDSA (X25519 + EdDSA via Signal Protocol C)
- `create_identity()` / `import_identity()` deprecated and raise `IdentityError`

## Archived Files

| File | Original Purpose |
|------|------------------|
| `test_identity_manager.py` | Tests for old `IdentityManager` with Ed25519/identity.json |
| `test_phase15_integration.py` | Integration tests using deprecated create_identity API |
| `test_dumb_relay.py` | Relay signer tests using old IdentityManager |
| `test_event_hash.py` | Tests for removed Ed25519 signing functions |

## Current Implementation

For the current XEdDSA-based implementation, see:
- `tests/python/test_xeddsa_e2e.py` - XEdDSA end-to-end tests
- `tests/python/test_mp2_identity_strict.py` - MP2 login with XEdDSA signatures
- `src/ming_drlms/core/pysignal/` - Signal Protocol Python bindings

**These tests are NOT run in CI and are kept for historical reference only.**
