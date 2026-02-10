"""Configuration registry and type system."""

from dataclasses import dataclass
from enum import Enum


class ConfigType(Enum):
    STRING = "string"
    INT = "int"
    BOOL = "bool"


@dataclass(frozen=True, slots=True)
class ConfigEntry:
    key: str
    type: ConfigType
    default: str | int | bool
    description: str
    secret: bool = False


REGISTRY: list[ConfigEntry] = [
    # -- server --
    ConfigEntry("server.host", ConfigType.STRING, "0.0.0.0", "Bind address for production server"),
    ConfigEntry("server.port", ConfigType.INT, 5001, "Port for production server"),
    ConfigEntry("server.dev_host", ConfigType.STRING, "127.0.0.1", "Bind address for dev server"),
    ConfigEntry("server.dev_port", ConfigType.INT, 5001, "Port for dev server"),
    ConfigEntry("server.debug", ConfigType.BOOL, False, "Enable Flask debug mode"),
    # -- gatekeeper --
    ConfigEntry("gatekeeper.db_path", ConfigType.STRING, "", "Path to Gatekeeper SQLite database"),
    ConfigEntry("gatekeeper.url", ConfigType.STRING, "", "Gatekeeper HTTP API base URL"),
    ConfigEntry("gatekeeper.api_key", ConfigType.STRING, "", "Gatekeeper API key", secret=True),
    # -- uploads --
    ConfigEntry("uploads.max_size_mb", ConfigType.INT, 50, "Maximum upload size in MB"),
    # -- blobs --
    ConfigEntry("blobs.directory", ConfigType.STRING, "instance/blobs", "Blob storage directory"),
    # -- outbox --
    ConfigEntry("outbox.db_path", ConfigType.STRING, "", "Path to Outbox SQLite database"),
    ConfigEntry(
        "outbox.mail_sender", ConfigType.STRING, "", "Sender email address for notifications"
    ),
    # -- proxy --
    ConfigEntry("proxy.x_forwarded_for", ConfigType.INT, 0, "Trust X-Forwarded-For (hop count)"),
    ConfigEntry(
        "proxy.x_forwarded_proto", ConfigType.INT, 0, "Trust X-Forwarded-Proto (hop count)"
    ),
    ConfigEntry("proxy.x_forwarded_host", ConfigType.INT, 0, "Trust X-Forwarded-Host (hop count)"),
    ConfigEntry(
        "proxy.x_forwarded_prefix", ConfigType.INT, 0, "Trust X-Forwarded-Prefix (hop count)"
    ),
]

_REGISTRY_MAP: dict[str, ConfigEntry] = {e.key: e for e in REGISTRY}


def resolve_entry(key: str) -> ConfigEntry | None:
    return _REGISTRY_MAP.get(key)


def parse_value(entry: ConfigEntry, raw: str) -> str | int | bool:
    match entry.type:
        case ConfigType.STRING:
            return raw
        case ConfigType.INT:
            return int(raw)
        case ConfigType.BOOL:
            return raw.lower() in ("true", "1", "yes", "on")


def serialize_value(entry: ConfigEntry, value: str | int | bool) -> str:
    match entry.type:
        case ConfigType.BOOL:
            return "true" if value else "false"
        case _:
            return str(value)


KEY_MAP: dict[str, str] = {
    "server.host": "HOST",
    "server.port": "PORT",
    "server.dev_host": "DEV_HOST",
    "server.dev_port": "DEV_PORT",
    "server.debug": "DEBUG",
    "gatekeeper.db_path": "GATEKEEPER_DB_PATH",
    "gatekeeper.url": "GATEKEEPER_URL",
    "gatekeeper.api_key": "GATEKEEPER_API_KEY",
    "uploads.max_size_mb": "MAX_UPLOAD_SIZE_MB",
    "blobs.directory": "BLOBS_DIRECTORY",
    "outbox.db_path": "OUTBOX_DB_PATH",
    "outbox.mail_sender": "OUTBOX_MAIL_SENDER",
    "proxy.x_forwarded_for": "PROXY_X_FORWARDED_FOR",
    "proxy.x_forwarded_proto": "PROXY_X_FORWARDED_PROTO",
    "proxy.x_forwarded_host": "PROXY_X_FORWARDED_HOST",
    "proxy.x_forwarded_prefix": "PROXY_X_FORWARDED_PREFIX",
}
