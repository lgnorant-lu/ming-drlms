from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .config_paths import get_config_file

try:  # Python 3.11+
    import tomllib as _toml
except Exception:  # pragma: no cover
    import tomli as _toml  # type: ignore


@dataclass
class RelaySettings:
    base_url: str = ""
    enforce_signed: bool = True
    enforce_verify: bool = True


@dataclass
class MP2Settings:
    host: str = "127.0.0.1"
    port: int = 15035
    tls: bool = False


@dataclass
class P2PSecuritySettings:
    require_identity_sig: bool = True
    enforce_signed: bool = True
    strict_mode: bool = True
    identity_sig_max_skew: int = 300


@dataclass
class UpdateSettings:
    enable: bool = True


@dataclass
class LoggingSettings:
    level: str = "info"


@dataclass
class AppSettings:
    raw: Dict[str, Any]
    env: Mapping[str, str]
    config_path: Path


def _parse_toml_lenient(text: str) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    section: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            header = line[1:-1].strip()
            if not header:
                section = []
                continue
            section = header.split(".")
            cur: Dict[str, Any] = data
            for part in section:
                if not part:
                    continue
                node = cur.get(part)
                if not isinstance(node, dict):
                    node = {}
                    cur[part] = node
                cur = node
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        val = val.strip()
        if "#" in val:
            val, _ = val.split("#", 1)
            val = val.strip()
        if not val:
            continue
        if (len(val) >= 2) and (val[0] == val[-1]) and val[0] in ('"', "'"):
            value: Any = val[1:-1]
        elif val.lower() in ("true", "false"):
            value = val.lower() == "true"
        else:
            try:
                value = int(val)
            except Exception:
                try:
                    value = float(val)
                except Exception:
                    value = val
        cur = data
        for part in section:
            if not part:
                continue
            node = cur.get(part)
            if not isinstance(node, dict):
                node = {}
                cur[part] = node
            cur = node
        if isinstance(cur, dict):
            cur[key] = value
    return data


def _read_toml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as f:
            return _toml.load(f)
    except Exception:
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            return {}
        return _parse_toml_lenient(text)


def load_settings(env: Optional[Mapping[str, str]] = None) -> AppSettings:
    env = env or os.environ
    path = get_config_file()
    raw = _read_toml(path)
    return AppSettings(raw=raw, env=env, config_path=path)


def _general(s: AppSettings) -> Dict[str, Any]:
    g = s.raw.get("general")
    return g if isinstance(g, dict) else {}


def get_backend(s: AppSettings) -> str:
    # ENV override takes highest priority
    backend_env = s.env.get("DRLMS_BACKEND", "").strip().lower()
    if backend_env in ("mp2", "relay"):
        return backend_env
    # Preserve previous TUI semantics: when no explicit config dir is provided
    # via MING_DRLMS_CONFIG_DIR, default to MP2 so that developer-local configs
    # do not accidentally affect tests.
    if not s.env.get("MING_DRLMS_CONFIG_DIR"):
        return "mp2"
    # Read from config
    g = _general(s)
    b = str(g.get("backend", "")).strip().lower()
    if b in ("mp2", "relay"):
        return b
    # Heuristic fallback: if relay section present then relay, else mp2
    relay_cfg = g.get("relay") if isinstance(g, dict) else None
    if isinstance(relay_cfg, dict):
        return "relay"
    return "mp2"


def get_relay_settings(s: AppSettings) -> RelaySettings:
    g = _general(s)
    rcfg = g.get("relay") if isinstance(g, dict) else None
    base_url = ""
    enforce_signed = True
    enforce_verify = True
    if isinstance(rcfg, dict):
        base_url = str(rcfg.get("base_url", "")).strip()
        enforce_signed = bool(rcfg.get("enforce_signed", True))
        enforce_verify = bool(rcfg.get("enforce_verify", True))
    # ENV overrides
    env_base = s.env.get("DRLMS_RELAY_BASE_URL") or s.env.get("RELAY_BASE_URL")
    if env_base:
        base_url = str(env_base).strip()
    return RelaySettings(
        base_url=base_url, enforce_signed=enforce_signed, enforce_verify=enforce_verify
    )


def get_mp2_settings(s: AppSettings) -> MP2Settings:
    g = _general(s)
    mcfg = g.get("mp2") if isinstance(g, dict) else None
    host = "127.0.0.1"
    port = 15035
    tls = False
    if isinstance(mcfg, dict):
        host = str(mcfg.get("host", host))
        try:
            port = int(mcfg.get("port", port))
        except Exception:
            port = 15035
        tls = bool(mcfg.get("tls", tls))
    # ENV overrides
    host = str(s.env.get("DRLMS_MP2_HOST", host))
    try:
        port = int(s.env.get("DRLMS_MP2_PORT", port))
    except Exception:
        pass
    tls_env = s.env.get("DRLMS_MP2_TLS")
    if tls_env is not None:
        tls = str(tls_env).strip() not in ("0", "false", "False")
    return MP2Settings(host=host, port=port, tls=tls)


def get_p2p_security(s: AppSettings) -> P2PSecuritySettings:
    g = _general(s)
    scfg = g.get("security", {}) if isinstance(g, dict) else {}
    p2p = scfg.get("p2p", {}) if isinstance(scfg, dict) else {}
    # defaults: all strict enabled
    require_identity_sig = bool(p2p.get("require_identity_sig", True))
    enforce_signed = bool(p2p.get("enforce_signed", True))
    strict_mode = bool(p2p.get("strict_mode", True))
    try:
        identity_sig_max_skew = int(p2p.get("identity_sig_max_skew", 300))
    except Exception:
        identity_sig_max_skew = 300

    # emergency from config
    emerg = p2p.get("emergency", {}) if isinstance(p2p, dict) else {}
    disable_all_strict_cfg = bool(emerg.get("disable_all_strict", False))

    # ENV overrides
    # total override first
    strict_env = s.env.get("DRLMS_STRICT_P2P")
    if strict_env is not None:
        if str(strict_env) == "0":
            require_identity_sig = False
            enforce_signed = False
            strict_mode = False
        elif str(strict_env) == "1":
            require_identity_sig = True
            enforce_signed = True
            strict_mode = True
    # single toggles
    v = s.env.get("DRLMS_REQUIRE_IDENTITY_SIG")
    if v is not None:
        require_identity_sig = str(v) not in ("0", "false", "False")
    v = s.env.get("DRLMS_RELAY_ENFORCE_SIGNED")
    if v is not None:
        enforce_signed = str(v) not in ("0", "false", "False")
    v = s.env.get("DRLMS_RELAY_STRICT_MODE")
    if v is not None:
        strict_mode = str(v) not in ("0", "false", "False")
    v = s.env.get("DRLMS_IDENTITY_SIG_MAX_SKEW")
    if v is not None:
        try:
            identity_sig_max_skew = int(v)
        except Exception:
            pass

    # emergency from config (if true and no env total-override specified)
    if strict_env is None and disable_all_strict_cfg:
        require_identity_sig = False
        enforce_signed = False
        strict_mode = False

    return P2PSecuritySettings(
        require_identity_sig=require_identity_sig,
        enforce_signed=enforce_signed,
        strict_mode=strict_mode,
        identity_sig_max_skew=identity_sig_max_skew,
    )


def get_update_settings(s: AppSettings) -> UpdateSettings:
    g = _general(s)
    ucfg = g.get("update", {}) if isinstance(g, dict) else {}
    enable = bool(ucfg.get("enable", True))
    v = s.env.get("DRLMS_UPDATE_CHECK")
    if v is not None:
        enable = str(v) not in ("0", "false", "False")
    return UpdateSettings(enable=enable)


def get_logging_settings(s: AppSettings) -> LoggingSettings:
    g = _general(s)
    lcfg = g.get("logging", {}) if isinstance(g, dict) else {}
    level = str(lcfg.get("level", "info")).lower()
    v = s.env.get("DRLMS_LOG_LEVEL")
    if v:
        level = str(v).lower()
    return LoggingSettings(level=level)


def get_relays_config():
    """Load Phase 16A relays.toml configuration.

    Returns RelaysConfig from relay module, or None if not available/configured.
    """
    try:
        from .relay import RelaysConfig, get_default_config_path

        cfg_path = get_default_config_path()
        return RelaysConfig.load(cfg_path)
    except Exception:
        return None


def get_relay_urls(s: AppSettings) -> list[str]:
    """Get list of relay URLs from configuration.

    Priority:
    1. relays.toml (Phase 16A multi-relay config)
    2. settings.toml relay.base_url (legacy single relay)
    3. ENV DRLMS_RELAY_BASE_URL

    Returns:
        List of relay URLs, or empty list if none configured
    """
    urls: list[str] = []

    # 1. Try Phase 16A relays.toml
    relays_cfg = get_relays_config()
    if relays_cfg:
        for r in relays_cfg.get_primary_relays():
            if r.url:
                urls.append(r.url)

    # 2. Fallback to legacy single relay
    if not urls:
        legacy = get_relay_settings(s)
        if legacy.base_url:
            urls.append(legacy.base_url)

    return urls


def build_effective_view(s: AppSettings) -> Dict[str, Any]:
    """Return a simplified effective config view for diagnostics/CLI display."""
    return {
        "backend": get_backend(s),
        "relay": {
            "base_url": get_relay_settings(s).base_url,
            "enforce_signed": get_relay_settings(s).enforce_signed,
            "enforce_verify": get_relay_settings(s).enforce_verify,
        },
        "mp2": {
            "host": get_mp2_settings(s).host,
            "port": get_mp2_settings(s).port,
            "tls": get_mp2_settings(s).tls,
        },
        "security": {
            "p2p": {
                "require_identity_sig": get_p2p_security(s).require_identity_sig,
                "enforce_signed": get_p2p_security(s).enforce_signed,
                "strict_mode": get_p2p_security(s).strict_mode,
                "identity_sig_max_skew": get_p2p_security(s).identity_sig_max_skew,
            }
        },
        "update": {"enable": get_update_settings(s).enable},
        "logging": {"level": get_logging_settings(s).level},
    }


__all__ = [
    "AppSettings",
    "load_settings",
    "get_backend",
    "get_relay_settings",
    "get_mp2_settings",
    "get_p2p_security",
    "get_update_settings",
    "get_logging_settings",
    "build_effective_view",
]
