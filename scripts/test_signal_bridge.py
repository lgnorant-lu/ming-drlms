#!/usr/bin/env python3
"""Test signal bridge loading and FFI compatibility."""

import sys
import os

# Ensure we use the local source
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Set config dir
os.environ.setdefault(
    "MING_DRLMS_CONFIG_DIR", os.path.join(os.path.dirname(__file__), "..", ".drlms")
)

print("=== Testing signal bridge ===")

try:
    from ming_drlms.core._pysignal_bridge import load_bridge

    print("1. Importing load_bridge... OK")

    ffi, lib = load_bridge()
    print(f"2. load_bridge() returned: ffi={type(ffi)}, lib={type(lib)}")
    print(f"   ffi id: {id(ffi)}")

    # Test creating a signal_context**
    print("3. Testing ffi.new('signal_context **')...")
    ctx_ptr = ffi.new("signal_context **")
    print(f"   ctx_ptr type: {type(ctx_ptr)}")
    print(f"   ctx_ptr ffi: {ctx_ptr.ffi if hasattr(ctx_ptr, 'ffi') else 'N/A'}")

    # Test calling signal_context_create
    print("4. Testing lib.signal_context_create...")
    rc = lib.signal_context_create(ctx_ptr, ffi.NULL)
    print(f"   rc = {rc}")

    if rc == 0:
        print("5. Context created successfully!")
        # Clean up
        lib.signal_context_destroy(ctx_ptr[0])
        print("6. Context destroyed.")
    else:
        print(f"5. FAILED: rc = {rc}")

except TypeError as e:
    print(f"\n!!! TypeError: {e}")
    print("\nThis is the FFI instance mismatch issue.")

    # Debug info
    import traceback

    traceback.print_exc()

except Exception as e:
    print(f"\n!!! Exception: {type(e).__name__}: {e}")
    import traceback

    traceback.print_exc()
