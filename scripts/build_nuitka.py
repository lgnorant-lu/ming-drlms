#!/usr/bin/env python3
"""Build DRLMS with Nuitka into a standalone executable.

This script compiles the ming-drlms CLI (including the TUI) into a single
executable file using Nuitka.

Usage:
    python scripts/build_nuitka.py [--onefile] [--output-dir DIR]
"""

import argparse
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Build DRLMS with Nuitka")
    parser.add_argument(
        "--onefile",
        action="store_true",
        help="Build a single-file executable (slower startup, easier distribution)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("build/nuitka"),
        help="Output directory for build artifacts (default: build/nuitka)",
    )
    parser.add_argument(
        "--standalone",
        action="store_true",
        default=True,
        help="Build a standalone distribution (default: True)",
    )

    args = parser.parse_args()

    # Ensure output directory exists
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Warn if not in virtual environment
    in_venv = hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    )
    if not in_venv:
        print("⚠️  WARNING: Not running in a virtual environment!")
        print("   Build may use system packages (Debian/Ubuntu), reducing portability.")
        print(
            "   Recommended: Create venv with 'python -m venv .venv' and install deps there."
        )
        print()

    # Base Nuitka command
    cmd = [
        sys.executable,
        "-m",
        "nuitka",
        "--standalone" if args.standalone else "--module",
        "--output-dir=" + str(args.output_dir),
        "--include-package=ming_drlms",
        "--include-package=textual",
        "--include-package=typer",
        "--include-package=rich",
        "--include-data-files=src/ming_drlms/core/_pysignal_runtime.c=ming_drlms/core/_pysignal_runtime.c",
        # Note: anti-bloat plugin is auto-enabled in recent Nuitka versions
        "--follow-imports",
        "--assume-yes-for-downloads",
        "--python-flag=no_site",
        "src/ming_drlms/main.py",
    ]

    if args.onefile:
        cmd.insert(3, "--onefile")

    print("=" * 60)
    print("Building ming-drlms with Nuitka")
    print("=" * 60)
    print(f"Command: {' '.join(cmd)}")
    print()

    try:
        subprocess.run(cmd, check=True)
        print()
        print("=" * 60)
        print("✅ Build successful!")
        print("=" * 60)
        print(f"Output directory: {args.output_dir}")

        # Find and report the executable
        if args.onefile:
            exe_pattern = "main.bin" if sys.platform != "win32" else "main.exe"
        else:
            exe_pattern = (
                "main.dist/main" if sys.platform != "win32" else "main.dist/main.exe"
            )

        exe_path = args.output_dir / exe_pattern
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            print(f"Executable: {exe_path}")
            print(f"Size: {size_mb:.2f} MB")
        else:
            print(f"⚠️  Could not find executable at expected location: {exe_path}")
            print("Listing output directory:")
            for item in args.output_dir.rglob("*"):
                if item.is_file():
                    print(f"  {item.relative_to(args.output_dir)}")

        return 0

    except subprocess.CalledProcessError as e:
        print()
        print("=" * 60)
        print("❌ Build failed!")
        print("=" * 60)
        print(f"Exit code: {e.returncode}")
        return e.returncode
    except Exception as e:
        print()
        print("=" * 60)
        print("❌ Unexpected error!")
        print("=" * 60)
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
