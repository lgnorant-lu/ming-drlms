from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any, Dict
import os
import yaml


@dataclass
class CLIConfig:
    port: int = 8080
    data_dir: Path = Path("server_files")
    strict: bool = True
    max_conn: int = 128
    rate_up_bps: int = 0
    rate_down_bps: int = 0
    max_upload: int = 100 * 1024 * 1024


def _from_env(cfg: CLIConfig) -> CLIConfig:
    def getenv_int(name: str, default: int) -> int:
        v = os.environ.get(name)
        if v is None or v == "":
            return default
        try:
            return int(v)
        except Exception:
            return default

    strict_env = os.environ.get("DRLMS_AUTH_STRICT")
    return CLIConfig(
        port=getenv_int("DRLMS_PORT", cfg.port),
        data_dir=Path(os.environ.get("DRLMS_DATA_DIR", str(cfg.data_dir))),
        strict=(
            cfg.strict
            if strict_env is None
            else (strict_env not in ("0", "false", "False"))
        ),
        max_conn=getenv_int("DRLMS_MAX_CONN", cfg.max_conn),
        rate_up_bps=getenv_int("DRLMS_RATE_UP_BPS", cfg.rate_up_bps),
        rate_down_bps=getenv_int("DRLMS_RATE_DOWN_BPS", cfg.rate_down_bps),
        max_upload=getenv_int("DRLMS_MAX_UPLOAD", cfg.max_upload),
    )


def _merge(base: CLIConfig, override: Dict[str, Any]) -> CLIConfig:
    data = base.__dict__.copy()
    for k, v in override.items():
        if v is None:
            continue
        if k == "data_dir" and isinstance(v, str):
            data[k] = Path(v)
        else:
            data[k] = v
    return CLIConfig(**data)


def load_config(path: Optional[Path]) -> CLIConfig:
    cfg = CLIConfig()
    if path is None:
        default = Path.cwd() / "drlms.yaml"
        if default.exists():
            path = default
    if path and Path(path).exists():
        with open(path, "r") as f:
            y = yaml.safe_load(f) or {}
        cfg = _merge(cfg, y)
    cfg = _from_env(cfg)
    return cfg


def write_template(path: Path) -> None:
    tpl = {
        "port": 8080,
        "data_dir": "server_files",
        "strict": True,
        "max_conn": 128,
        "rate_up_bps": 0,
        "rate_down_bps": 0,
        "max_upload": 104857600,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump(tpl, f, sort_keys=False)
