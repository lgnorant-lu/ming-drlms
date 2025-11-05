from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any, Dict
import os
import yaml


@dataclass
class FederationServerConfig:
    server_id: str
    host: str
    port: int
    bearer_token: str


@dataclass
class FederationConfig:
    enabled: bool = False
    server_id: str = "server-a"
    bearer_token: str = "changeme-secret-token-phase4"
    trusted_servers: list[FederationServerConfig] = None

    def __post_init__(self):
        if self.trusted_servers is None:
            self.trusted_servers = []


@dataclass
class CLIConfig:
    port: int = 8080
    data_dir: Path = Path("server_files")
    strict: bool = True
    max_conn: int = 128
    rate_up_bps: int = 0
    rate_down_bps: int = 0
    max_upload: int = 100 * 1024 * 1024
    rooms_default_instance_capacity: int = 50
    rooms_max_instances: int = 20
    rooms_instance_idle_ttl: int = 86400
    rooms_instance_gc_interval: int = 60
    rooms_ephemeral_history_limit: int = 1000
    federation: FederationConfig = None

    def __post_init__(self):
        if self.federation is None:
            self.federation = FederationConfig()


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
        rooms_default_instance_capacity=getenv_int(
            "DRLMS_DEFAULT_INSTANCE_CAPACITY",
            cfg.rooms_default_instance_capacity,
        ),
        rooms_max_instances=getenv_int(
            "DRLMS_MAX_INSTANCES_PER_ROOM",
            cfg.rooms_max_instances,
        ),
        rooms_instance_idle_ttl=getenv_int(
            "DRLMS_INSTANCE_IDLE_TTL",
            cfg.rooms_instance_idle_ttl,
        ),
        rooms_instance_gc_interval=getenv_int(
            "DRLMS_INSTANCE_GC_INTERVAL",
            cfg.rooms_instance_gc_interval,
        ),
        rooms_ephemeral_history_limit=getenv_int(
            "DRLMS_EPHEMERAL_HISTORY_LIMIT",
            cfg.rooms_ephemeral_history_limit,
        ),
    )


def _merge(base: CLIConfig, override: Dict[str, Any]) -> CLIConfig:
    data = base.__dict__.copy()
    rooms = override.get("rooms") if isinstance(override, dict) else None
    if isinstance(rooms, dict):
        if "default_instance_capacity" in rooms:
            data["rooms_default_instance_capacity"] = int(
                rooms["default_instance_capacity"]
            )
        if "max_instances_per_room" in rooms:
            data["rooms_max_instances"] = int(rooms["max_instances_per_room"])
        if "instance_idle_ttl" in rooms:
            data["rooms_instance_idle_ttl"] = int(rooms["instance_idle_ttl"])
        if "instance_gc_interval" in rooms:
            data["rooms_instance_gc_interval"] = int(rooms["instance_gc_interval"])
        if "ephemeral_history_limit" in rooms:
            data["rooms_ephemeral_history_limit"] = int(
                rooms["ephemeral_history_limit"]
            )

    # Parse federation config
    federation = override.get("federation") if isinstance(override, dict) else None
    if isinstance(federation, dict):
        fed_enabled = federation.get("enabled", False)
        fed_server_id = federation.get("server_id", "server-a")
        fed_bearer_token = federation.get(
            "bearer_token", "changeme-secret-token-phase4"
        )
        fed_trusted = []
        trusted_list = federation.get("trusted_servers", [])
        if isinstance(trusted_list, list):
            for srv in trusted_list:
                if isinstance(srv, dict):
                    fed_trusted.append(
                        FederationServerConfig(
                            server_id=srv.get("server_id", ""),
                            host=srv.get("host", "localhost"),
                            port=int(srv.get("port", 19091)),
                            bearer_token=srv.get("bearer_token", ""),
                        )
                    )
        data["federation"] = FederationConfig(
            enabled=fed_enabled,
            server_id=fed_server_id,
            bearer_token=fed_bearer_token,
            trusted_servers=fed_trusted,
        )

    for k, v in override.items():
        if k in ("rooms", "federation"):
            continue
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
        "rooms": {
            "default_instance_capacity": 50,
            "max_instances_per_room": 20,
            "instance_idle_ttl": 86400,
            "instance_gc_interval": 60,
            "ephemeral_history_limit": 1000,
        },
        "federation": {
            "enabled": False,
            "server_id": "server-a",
            "bearer_token": "changeme-secret-token-phase4",
            "trusted_servers": [
                {
                    "server_id": "server-b",
                    "host": "localhost",
                    "port": 19091,
                    "bearer_token": "changeme-secret-token-phase4",
                }
            ],
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump(tpl, f, sort_keys=False)
