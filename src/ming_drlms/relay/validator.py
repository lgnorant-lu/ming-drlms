"""Phase 16B: Event Validator Module.

Implements defensive validation for relay events:
1. Event ID verification (recompute and compare)
2. XEdDSA signature verification
3. Timestamp reasonability check
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any, Callable

logger = logging.getLogger(__name__)


class ValidationError(Enum):
    """Types of validation errors."""

    INVALID_EVENT_ID = "invalid_event_id"
    SIGNATURE_VERIFICATION_FAILED = "signature_verification_failed"
    TIMESTAMP_OUT_OF_RANGE = "timestamp_out_of_range"
    MISSING_REQUIRED_FIELD = "missing_required_field"
    MALFORMED_DATA = "malformed_data"


@dataclass
class ValidationResult:
    """Result of event validation."""

    valid: bool
    errors: list[tuple[ValidationError, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, error_type: ValidationError, message: str) -> None:
        """Add a validation error."""
        self.valid = False
        self.errors.append((error_type, message))

    def add_warning(self, message: str) -> None:
        """Add a validation warning (doesn't fail validation)."""
        self.warnings.append(message)

    @property
    def error_messages(self) -> list[str]:
        """Get list of error messages."""
        return [f"{e[0].value}: {e[1]}" for e in self.errors]


@dataclass
class ValidationStats:
    """Statistics for validation operations."""

    total_validated: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    errors_by_type: dict[ValidationError, int] = field(
        default_factory=lambda: {e: 0 for e in ValidationError}
    )

    @property
    def validity_rate(self) -> float:
        """Percentage of valid events."""
        if self.total_validated == 0:
            return 100.0
        return self.valid_count / self.total_validated * 100


class EventValidator:
    """Defensive event validator.

    Performs multiple validation checks on events:
    1. Event ID recomputation and verification
    2. XEdDSA signature verification (when verifier available)
    3. Timestamp bounds checking

    Note: Signature verification requires XEdDSA library support.
    If unavailable, signature checks are skipped with a warning.
    """

    # Default: ±5 minutes
    DEFAULT_MAX_CLOCK_SKEW_MS = 5 * 60 * 1000

    def __init__(
        self,
        max_clock_skew_ms: int = DEFAULT_MAX_CLOCK_SKEW_MS,
        signature_verifier: Optional[Callable[[bytes, bytes, bytes], bool]] = None,
        strict_mode: bool = False,
    ):
        """Initialize the validator.

        Args:
            max_clock_skew_ms: Maximum allowed timestamp deviation from now
            signature_verifier: Optional function to verify XEdDSA signatures
                               Signature: (signature, public_key, message) -> bool
            strict_mode: If True, missing signature verifier fails validation
        """
        self._max_clock_skew_ms = max_clock_skew_ms
        self._signature_verifier = signature_verifier
        self._strict_mode = strict_mode
        self._stats = ValidationStats()

    @property
    def stats(self) -> ValidationStats:
        """Get validation statistics."""
        return self._stats

    def validate(self, event: dict[str, Any]) -> ValidationResult:
        """Validate an event.

        Expected event structure:
        {
            "event_id": str,           # sha256(sender_pubkey + content + timestamp)
            "sender_pubkey_hex": str,  # Sender's public key (hex)
            "content_bytes_b64": str,  # Content (base64)
            "timestamp_ms": int,       # Unix timestamp in milliseconds
            "signature_hex": str,      # XEdDSA signature (hex)
        }

        Args:
            event: Event dictionary to validate

        Returns:
            ValidationResult with valid flag and any errors
        """
        result = ValidationResult(valid=True)
        self._stats.total_validated += 1

        # Check required fields
        required_fields = ["event_id", "sender_pubkey_hex", "timestamp_ms"]
        for name in required_fields:
            if name not in event:
                result.add_error(
                    ValidationError.MISSING_REQUIRED_FIELD,
                    f"Missing required field: {name}",
                )
                self._record_error(ValidationError.MISSING_REQUIRED_FIELD)

        if not result.valid:
            self._stats.invalid_count += 1
            return result

        # 1. Verify event_id
        self._validate_event_id(event, result)

        # 2. Verify signature
        self._validate_signature(event, result)

        # 3. Verify timestamp
        self._validate_timestamp(event, result)

        # Update stats
        if result.valid:
            self._stats.valid_count += 1
        else:
            self._stats.invalid_count += 1

        return result

    def _validate_event_id(
        self, event: dict[str, Any], result: ValidationResult
    ) -> None:
        """Validate that event_id matches recomputed hash."""
        try:
            from ..core.event_hash import compute_event_id
            import base64

            sender_pubkey_hex = event.get("sender_pubkey_hex", "")
            content_b64 = event.get("content_bytes_b64", "")
            timestamp_ms = event.get("timestamp_ms", 0)

            # Decode content if base64 encoded
            try:
                content_bytes = base64.b64decode(content_b64) if content_b64 else b""
            except Exception:
                content_bytes = (
                    content_b64.encode() if isinstance(content_b64, str) else b""
                )

            # Convert pubkey hex to bytes
            try:
                sender_pubkey = (
                    bytes.fromhex(sender_pubkey_hex) if sender_pubkey_hex else b""
                )
            except ValueError:
                result.add_error(
                    ValidationError.MALFORMED_DATA,
                    "Invalid sender_pubkey_hex format",
                )
                self._record_error(ValidationError.MALFORMED_DATA)
                return

            # Compute expected event_id
            expected_id = compute_event_id(sender_pubkey, content_bytes, timestamp_ms)
            actual_id = event.get("event_id", "")

            if expected_id != actual_id:
                result.add_error(
                    ValidationError.INVALID_EVENT_ID,
                    f"Event ID mismatch: expected {expected_id[:16]}..., got {actual_id[:16]}...",
                )
                self._record_error(ValidationError.INVALID_EVENT_ID)
                logger.warning(
                    "Event ID verification failed: expected=%s actual=%s",
                    expected_id[:16],
                    actual_id[:16],
                )

        except ImportError:
            result.add_warning(
                "event_hash module not available, skipping ID verification"
            )
        except Exception as e:
            result.add_error(
                ValidationError.MALFORMED_DATA,
                f"Error computing event_id: {e}",
            )
            self._record_error(ValidationError.MALFORMED_DATA)

    def _validate_signature(
        self, event: dict[str, Any], result: ValidationResult
    ) -> None:
        """Validate XEdDSA signature."""
        signature_hex = event.get("signature_hex")

        if not signature_hex:
            if self._strict_mode:
                result.add_error(
                    ValidationError.MISSING_REQUIRED_FIELD,
                    "Missing signature in strict mode",
                )
                self._record_error(ValidationError.MISSING_REQUIRED_FIELD)
            else:
                result.add_warning("No signature present, skipping verification")
            return

        if not self._signature_verifier:
            if self._strict_mode:
                result.add_error(
                    ValidationError.SIGNATURE_VERIFICATION_FAILED,
                    "Signature verifier not available in strict mode",
                )
                self._record_error(ValidationError.SIGNATURE_VERIFICATION_FAILED)
            else:
                result.add_warning("Signature verifier not configured, skipping")
            return

        try:
            import base64

            # Decode signature
            signature = bytes.fromhex(signature_hex)

            # Decode public key
            sender_pubkey_hex = event.get("sender_pubkey_hex", "")
            public_key = bytes.fromhex(sender_pubkey_hex)

            # Get content to verify (the signed message)
            # Note: The actual signed content depends on the envelope format
            content_b64 = event.get("content_bytes_b64", "")
            content = base64.b64decode(content_b64) if content_b64 else b""

            # Verify signature
            if not self._signature_verifier(signature, public_key, content):
                result.add_error(
                    ValidationError.SIGNATURE_VERIFICATION_FAILED,
                    "XEdDSA signature verification failed",
                )
                self._record_error(ValidationError.SIGNATURE_VERIFICATION_FAILED)
                logger.warning(
                    "Signature verification failed for event %s",
                    event.get("event_id", "?")[:16],
                )

        except ValueError as e:
            result.add_error(
                ValidationError.MALFORMED_DATA,
                f"Invalid signature/key format: {e}",
            )
            self._record_error(ValidationError.MALFORMED_DATA)
        except Exception as e:
            result.add_error(
                ValidationError.SIGNATURE_VERIFICATION_FAILED,
                f"Signature verification error: {e}",
            )
            self._record_error(ValidationError.SIGNATURE_VERIFICATION_FAILED)

    def _validate_timestamp(
        self, event: dict[str, Any], result: ValidationResult
    ) -> None:
        """Validate timestamp is within acceptable range."""
        timestamp_ms = event.get("timestamp_ms", 0)

        if not isinstance(timestamp_ms, (int, float)):
            result.add_error(
                ValidationError.MALFORMED_DATA,
                f"Invalid timestamp type: {type(timestamp_ms)}",
            )
            self._record_error(ValidationError.MALFORMED_DATA)
            return

        now_ms = int(time.time() * 1000)
        diff_ms = abs(timestamp_ms - now_ms)

        if diff_ms > self._max_clock_skew_ms:
            result.add_error(
                ValidationError.TIMESTAMP_OUT_OF_RANGE,
                f"Timestamp {timestamp_ms} is {diff_ms}ms from current time "
                f"(max allowed: {self._max_clock_skew_ms}ms)",
            )
            self._record_error(ValidationError.TIMESTAMP_OUT_OF_RANGE)
            logger.warning(
                "Timestamp out of range: event_ts=%d now=%d diff=%dms",
                timestamp_ms,
                now_ms,
                diff_ms,
            )

    def _record_error(self, error_type: ValidationError) -> None:
        """Record an error in statistics."""
        self._stats.errors_by_type[error_type] += 1

    def reset_stats(self) -> None:
        """Reset validation statistics."""
        self._stats = ValidationStats()

    def set_signature_verifier(
        self, verifier: Callable[[bytes, bytes, bytes], bool]
    ) -> None:
        """Set the signature verifier function.

        Args:
            verifier: Function (signature, public_key, message) -> bool
        """
        self._signature_verifier = verifier


def create_xeddsa_verifier() -> Optional[Callable[[bytes, bytes, bytes], bool]]:
    """Create an XEdDSA signature verifier using the Signal library.

    Returns:
        Verifier function or None if library not available
    """
    try:
        from ..core.pysignal.signature import verify_bytes

        def verifier(signature: bytes, public_key: bytes, message: bytes) -> bool:
            try:
                return verify_bytes(signature, public_key, message)
            except Exception:
                return False

        return verifier
    except ImportError:
        logger.debug("pysignal not available, XEdDSA verifier not created")
        return None


__all__ = [
    "ValidationError",
    "ValidationResult",
    "ValidationStats",
    "EventValidator",
    "create_xeddsa_verifier",
]
