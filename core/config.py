"""Load TOML config and required environment variables; fail fast on anything missing."""

import os
import tomllib
from pathlib import Path

CONFIG_DIR = Path("config")


class ConfigError(Exception):
    """Raised when config or environment is incomplete. The message says how to fix it."""


def load_toml(path: Path) -> dict:
    if not path.exists():
        example = path.with_suffix(".example.toml")
        raise ConfigError(f"{path} not found — copy {example} and fill it in")
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path} is not valid TOML: {e}") from e


def _require_keys(data: dict, keys: list[str], path: Path) -> None:
    missing = [k for k in keys if k not in data]
    if missing:
        raise ConfigError(f"{path} is missing: {', '.join(missing)}")


def load_config(config_dir: Path = CONFIG_DIR) -> dict:
    """Return {"targets": [company, ...], "profile": {...}}."""
    targets_path = config_dir / "targets.toml"
    profile_path = config_dir / "profile.toml"

    targets = load_toml(targets_path)
    _require_keys(targets, ["company"], targets_path)

    profile = load_toml(profile_path)
    _require_keys(profile, ["filter", "scoring"], profile_path)

    return {"targets": targets["company"], "profile": profile}


def require_env(names: list[str]) -> dict[str, str]:
    """Return the named env vars. Raise one error listing every missing or empty name."""
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise ConfigError(
            f"missing environment variables: {', '.join(missing)} "
            "— see .env.example, then run: set -a; source .env; set +a"
        )
    return {n: os.environ[n] for n in names}
