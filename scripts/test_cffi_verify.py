#!/usr/bin/env python3
"""Test CFFI verify() module structure."""

from cffi import FFI

ffi = FFI()
ffi.cdef("int abs(int);")
mod = ffi.verify("#include <stdlib.h>")

print("module type:", type(mod))
print("has ffi attr:", hasattr(mod, "ffi"))
print("dir(mod):", [x for x in dir(mod) if not x.startswith("_")])

# Check if the original ffi can be used with the module
print("\n--- Testing type compatibility ---")
try:
    # This should work if ffi and mod are compatible
    result = mod.abs(-5)
    print("mod.abs(-5) =", result)
except Exception as e:
    print("Error calling mod.abs:", e)
