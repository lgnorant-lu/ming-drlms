# Legacy Scripts (Phase 15 / Ed25519)

These scripts are archived from the Phase 15 implementation when
`IdentityManager` used standalone Ed25519 keys stored in `identity.json`.

**Phase 15.5 Migration**:
- Identity storage unified to `LocalKeyStore` (`e2ee_keys.json`)
- Ed25519 replaced by XEdDSA (X25519 + EdDSA via Signal Protocol C)

## Archived Files

| File | Original Purpose |
|------|------------------|
| `test_signature_tamper.py` | Signature tampering tests using old IdentityManager |

## Current Implementation

For the current XEdDSA-based implementation, see:
- `src/ming_drlms/core/relay_signer.py` - RelaySigner with XEdDSA
- `src/ming_drlms/core/pysignal/signature.py` - XEdDSA sign/verify

**These scripts are NOT maintained and are kept for historical reference only.**
