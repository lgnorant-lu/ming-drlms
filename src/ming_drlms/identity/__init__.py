"""Phase 18A: Local identity and trust management for Relay decentralization.

This package provides:
- LocalIdentityManager: Create/restore identities locally without server
- TrustStore: Multi-level trust model (TOFU → Manual → Social → Anchored)
- Anchors: External identity verification (DNS, HTTPS, GitHub)
- Verification: Manual verification utilities (fingerprint, QR code)
"""

from .local_identity import (
    LocalIdentity,
    LocalIdentityManager,
    generate_fingerprint,
    format_fingerprint,
)
from .trust_store import (
    TrustLevel,
    TrustRecord,
    TrustStore,
    KeyChangeEvent,
    KeyChangePolicy,
)
from .anchors import (
    AnchorVerifier,
    AnchorResult,
    DNSAnchorVerifier,
    HTTPSAnchorVerifier,
    GitHubAnchorVerifier,
    verify_anchor,
    AnchorError,
)
from .verification import (
    VerificationSession,
    FingerprintDisplay,
    compare_fingerprints,
    create_verification_qr_data,
    parse_verification_qr_data,
    VerificationUI,
)

__all__ = [
    # Identity
    "LocalIdentity",
    "LocalIdentityManager",
    "generate_fingerprint",
    "format_fingerprint",
    # Trust
    "TrustLevel",
    "TrustRecord",
    "TrustStore",
    "KeyChangeEvent",
    "KeyChangePolicy",
    # Anchors
    "AnchorVerifier",
    "AnchorResult",
    "DNSAnchorVerifier",
    "HTTPSAnchorVerifier",
    "GitHubAnchorVerifier",
    "verify_anchor",
    "AnchorError",
    # Verification
    "VerificationSession",
    "FingerprintDisplay",
    "compare_fingerprints",
    "create_verification_qr_data",
    "parse_verification_qr_data",
    "VerificationUI",
]
