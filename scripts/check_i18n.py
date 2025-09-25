from __future__ import annotations

import json
from pathlib import Path
import sys


def load(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> int:
    base = Path(__file__).resolve().parents[1] / "gui_poc" / "i18n"
    en = load(base / "en.json")
    zh = load(base / "zh.json")
    en_keys = set(en.keys())
    zh_keys = set(zh.keys())
    missing_en = zh_keys - en_keys
    missing_zh = en_keys - zh_keys
    rc = 0
    if missing_en:
        print("[i18n] keys missing in en:", sorted(missing_en))
        rc = 1
    if missing_zh:
        print("[i18n] keys missing in zh:", sorted(missing_zh))
        rc = 1
    if rc == 0:
        print("[i18n] en/zh keys are consistent.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
