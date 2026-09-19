"""Загрузка и валидация конфигурации бота."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

from markup import MarkupTier, parse_tiers
from nav import (
    DEFAULT_BUTTON_STYLE,
    DEFAULT_COLUMNS,
    DEFAULT_ROW_WIDTH,
    DEFAULT_NAV_TEXT,
    ButtonStyleError,
    validate_style,
)
from renderer import DEFAULT_PRICE_FORMAT, PriceFormatError, validate_price_format

DEFAULT_CONFIG_PATH = Path("config.yaml")


class ConfigError(ValueError):
    """Конфигурация некорректна."""


@dataclass(frozen=True)
class OrderButton:
    """Кнопка «Заказать» под каждым постом."""

    text: str
    url: str
    style: str = DEFAULT_BUTTON_STYLE


@dataclass(frozen=True)
class Config:
    """Разобранная конфигурация запуска."""

    bot_token: str
    source_channel: str
    target_chat_id: str
    target_channel: str | None
    tiers: tuple[MarkupTier, ...]
    round_to_nearest: int
    price_format: str
    check_interval: int
    max_scan_pages: int
    categories: tuple[str, ...]
    deny_categories: tuple[str, ...]
    allow_create: bool
    disable_notification: bool
    nav_enabled: bool
    nav_text: str
    nav_columns: int
    nav_row_width: int
    nav_pin: bool
    nav_button_style: str
    order_button: OrderButton | None
    info_enabled: bool
    info_file: Path
    excel_enabled: bool
    excel_publish: bool
    excel_output_dir: Path
    excel_filename: str
    excel_button_text: str
    excel_button_style: str
    proxy: str | None


def _require(raw: dict, key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"В config.yaml нужен непустой '{key}'")
    return value.strip()


def _optional_str(raw: dict, key: str) -> str | None:
    value = raw.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise ConfigError(f"'{key}' должен быть строкой")
    return value.strip()


def _positive_int(raw: dict, key: str, default: int) -> int:
    value = raw.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"'{key}' должен быть положительным целым")
    return value


def _string_list(raw: dict, key: str) -> tuple[str, ...]:
    value = raw.get(key) or []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ConfigError(f"'{key}' должен быть списком строк")
    return tuple(item.strip() for item in value if item.strip())


def _parse_order_button(raw: dict) -> OrderButton | None:
    value = raw.get("order_button")
    if not value:
        return None
    if not isinstance(value, dict):
        raise ConfigError("'order_button' должен быть словарём с 'text' и 'url'")
    text, url = value.get("text"), value.get("url")
    if not isinstance(text, str) or not text.strip():
        raise ConfigError("'order_button.text' должен быть непустой строкой")
    if not isinstance(url, str) or not url.startswith(("https://", "http://", "tg://")):
        raise ConfigError("'order_button.url' должен быть ссылкой https:// или tg://")
    style = value.get("style", DEFAULT_BUTTON_STYLE)
    if not isinstance(style, str):
        raise ConfigError("'order_button.style' должен быть строкой")
    try:
        validate_style(style)
    except ButtonStyleError as exc:
        raise ConfigError(f"order_button: {exc}") from exc
    return OrderButton(text=text.strip(), url=url.strip(), style=style)


def load_config(path: Path = DEFAULT_CONFIG_PATH, *, require_token: bool = True) -> Config:
    """Прочитать config.yaml и .env, вернуть валидированный Config.

    require_token=False нужен режимам, которые не ходят в Bot API (--seed, --dry-run).
    """
    load_dotenv(path.parent / ".env" if path.parent.name else ".env")

    if not path.exists():
        raise ConfigError(f"Файл конфигурации не найден: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError("config.yaml должен содержать словарь на верхнем уровне")

    # У каждого канала свой бот, поэтому имя переменной с токеном задаётся
    # в конфиге: так один кодовый базис обслуживает несколько каналов.
    token_env = raw.get("bot_token_env", "BOT_TOKEN")
    if not isinstance(token_env, str) or not token_env.strip():
        raise ConfigError("'bot_token_env' должен быть непустой строкой")
    token_env = token_env.strip()

    token = os.environ.get(token_env, "").strip()
    if require_token and not token:
        raise ConfigError(f"Не задан {token_env} (положите его в .env)")

    round_to = raw.get("round_to_nearest", 0)
    if not isinstance(round_to, int) or isinstance(round_to, bool) or round_to < 0:
        raise ConfigError("'round_to_nearest' должен быть неотрицательным целым")

    price_format = raw.get("price_format", DEFAULT_PRICE_FORMAT)
    if not isinstance(price_format, str):
        raise ConfigError("'price_format' должен быть строкой")
    try:
        validate_price_format(price_format)
    except PriceFormatError as exc:
        raise ConfigError(str(exc)) from exc

    tiers_raw = raw.get("markup_tiers")
    if not isinstance(tiers_raw, list):
        raise ConfigError("В config.yaml нужен список 'markup_tiers'")

    nav_raw = raw.get("nav") or {}
    if not isinstance(nav_raw, dict):
        raise ConfigError("'nav' должен быть словарём")

    info_raw = raw.get("info_message") or {}
    if not isinstance(info_raw, dict):
        raise ConfigError("'info_message' должен быть словарём")
    info_file = Path(str(info_raw.get("file") or "info.html"))
    info_enabled = bool(info_raw.get("enabled", False))
    if info_enabled and not info_file.exists():
        raise ConfigError(f"Файл информационного сообщения не найден: {info_file}")

    excel_raw = raw.get("excel") or {}
    if not isinstance(excel_raw, dict):
        raise ConfigError("'excel' должен быть словарём")
    excel_output_dir = Path(str(excel_raw.get("output_dir") or "_excel"))
    excel_filename = str(excel_raw.get("filename") or "price_{date}.xlsx")
    if not excel_filename.lower().endswith(".xlsx"):
        raise ConfigError("'excel.filename' должен заканчиваться на .xlsx")
    excel_style = excel_raw.get("button_style", "success")
    if not isinstance(excel_style, str):
        raise ConfigError("'excel.button_style' должен быть строкой")
    try:
        validate_style(excel_style)
    except ButtonStyleError as exc:
        raise ConfigError(f"excel: {exc}") from exc

    nav_style = nav_raw.get("button_style", DEFAULT_BUTTON_STYLE)
    if not isinstance(nav_style, str):
        raise ConfigError("'nav.button_style' должен быть строкой")
    try:
        validate_style(nav_style)
    except ButtonStyleError as exc:
        raise ConfigError(f"nav: {exc}") from exc

    target_chat_id = raw.get("target_chat_id")
    if isinstance(target_chat_id, int):
        target_chat_id = str(target_chat_id)
    if not isinstance(target_chat_id, str) or not target_chat_id.strip():
        raise ConfigError("В config.yaml нужен непустой 'target_chat_id'")

    target_channel = _optional_str(raw, "target_channel")

    return Config(
        bot_token=token,
        source_channel=_require(raw, "source_channel").lstrip("@"),
        target_chat_id=target_chat_id.strip(),
        target_channel=target_channel.lstrip("@") if target_channel else None,
        tiers=parse_tiers(tiers_raw),
        round_to_nearest=round_to,
        price_format=price_format,
        check_interval=_positive_int(raw, "check_interval", 3600),
        max_scan_pages=_positive_int(raw, "max_scan_pages", 8),
        categories=_string_list(raw, "categories"),
        deny_categories=_string_list(raw, "deny_categories"),
        allow_create=bool(raw.get("allow_create", False)),
        disable_notification=bool(raw.get("disable_notification", True)),
        nav_enabled=bool(nav_raw.get("enabled", True)),
        nav_text=str(nav_raw.get("text") or DEFAULT_NAV_TEXT),
        nav_columns=_positive_int(nav_raw, "columns", DEFAULT_COLUMNS),
        nav_row_width=_positive_int(nav_raw, "row_width", DEFAULT_ROW_WIDTH),
        nav_pin=bool(nav_raw.get("pin", True)),
        nav_button_style=nav_style,
        order_button=_parse_order_button(raw),
        info_enabled=info_enabled,
        info_file=info_file,
        excel_enabled=bool(excel_raw.get("enabled", False)),
        excel_publish=bool(excel_raw.get("publish", False)),
        excel_output_dir=excel_output_dir,
        excel_filename=excel_filename,
        excel_button_text=str(excel_raw.get("button_text") or "Прайс EXCEL"),
        excel_button_style=excel_style,
        proxy=os.environ.get("TG_PROXY") or os.environ.get("T_ME_PROXY") or None,
    )
