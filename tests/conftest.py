"""Pytest configuration for ming-drlms tests.

This file ensures proper environment setup for all tests.
"""

import os
import sys
from pathlib import Path

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# Load environment variables from .env.local if it exists
env_local = project_root / ".env.local"
if env_local.exists():
    try:
        from dotenv import load_dotenv

        load_dotenv(env_local)
        print(f"✓ Loaded environment from {env_local}")
    except ImportError:
        # dotenv not available, manually parse critical vars
        with open(env_local) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    if key == "LIBOQS_DIR":
                        os.environ[key] = value
                        print(f"✓ Set {key}={value}")
