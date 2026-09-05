"""Оркестрация: чтение источника, пересчёт цен, публикация в целевой канал."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

import aiohttp

from bot_api import NOT_MODIFIED, BotApi
from catalog import Category, build_categories, normalize_key
from config import Config
from excel import build_caption, build_filename, build_workbook, collect_rows, rows_hash
from nav import build_keyboard, make_button, message_link, render_text
from renderer import TELEGRAM_MAX_LEN, build_messages, count_price_lines
from state import CategorySlot, State, save_state
from tme_scraper import fetch_messages

log = logging.getLogger(__name__)

# Telegram ограничивает бота примерно 20 сообщениями в минуту на чат — и отправка,
# и правка считаются вместе. Замерено на живом канале: при 2 с прилетает 429.
# Паузы держат нас ниже лимита, ретрай по retry_after остаётся страховкой.
EDIT_DELAY_SECONDS = 3.5
CREATE_DELAY_SECONDS = 4.0
_TRUNCATION_STEP = 5


def _http_proxy(cfg: Config) -> str | None:
    """HTTP(S)-прокси передаётся в aiohttp пер-запросно; SOCKS живёт в коннекторе."""
    if cfg.proxy and cfg.proxy.startswith(("http://", "https://")):
        return cfg.proxy
    return None


def content_hash(parts: list[str]) -> str:
    return hashlib.md5("\n\x00\n".join(parts).encode("utf-8")).hexdigest()


async def discover_slots(session: aiohttp.ClientSession, cfg: Config) -> dict[str, CategorySlot]:
    """Найти в публичном целевом канале готовые посты-прайсы и закрепить их за категориями."""
    if not cfg.target_channel:
        raise ValueError("Для --seed нужен публичный 'target_channel' в config.yaml")

    messages = await fetch_messages(
        session,
        cfg.target_channel,
        max_pages=cfg.max_scan_pages,
        http_proxy=_http_proxy(cfg),
    )
    categories = build_categories(messages)
    return {
        key: CategorySlot(title=category.title, message_ids=category.message_ids)
        for key, category in categories.items()
    }


async def fetch_source_categories(
    session: aiohttp.ClientSession, cfg: Config,
) -> dict[str, Category]:
    """Прочитать актуальный каталог канала-источника."""
    messages = await fetch_messages(
        session,
        cfg.source_channel,
        max_pages=cfg.max_scan_pages,
        http_proxy=_http_proxy(cfg),
    )
    return build_categories(messages)


def is_allowed(key: str, cfg: Config) -> bool:
    """Проверить категорию по спискам из конфига."""
    if any(key == normalize_key(name) for name in cfg.deny_categories):
        return False
    if not cfg.categories:
        return True
    return any(key == normalize_key(name) for name in cfg.categories)


def planned_keys(cfg: Config, state: State) -> list[str]:
    """Ключи категорий в том порядке, в котором их надо публиковать."""
    if cfg.categories:
        keys = [normalize_key(name) for name in cfg.categories]
    else:
        keys = list(state.slots)
    seen: set[str] = set()
    ordered = []
    for key in keys:
        if key in seen or not is_allowed(key, cfg):
            continue
        seen.add(key)
        ordered.append(key)
    return ordered


def _order_keyboard(cfg: Config) -> dict | None:
    if cfg.order_button is None:
        return None
    button = make_button(cfg.order_button.text, cfg.order_button.url, cfg.order_button.style)
    return {"inline_keyboard": [[button]]}


def _footer(dropped: int) -> str:
    return f"… ещё {dropped} позиций — уточняйте у менеджера"


def render_category(category: Category, slot: CategorySlot, cfg: Config) -> tuple[list[str], int]:
    """Собрать сообщения категории.

    Число частей берётся из уже занятых слотов, а для новой категории — из
    структуры источника. Возвращает (сообщения, число скрытых позиций).
    """
    slots = len(slot.message_ids) or max(1, len(category.parts))
    lines = category.lines
    parts = build_messages(
        category.title, lines, slots, cfg.tiers, cfg.round_to_nearest,
        price_format=cfg.price_format,
    )

    if len(parts) <= slots or cfg.allow_create:
        return parts, 0

    kept = list(lines)
    dropped = 0
    while kept and len(parts) > slots:
        for _ in range(_TRUNCATION_STEP):
            if not kept:
                break
            removed = kept.pop()
            if removed.strip():
                dropped += 1
        body = kept + ["", _footer(dropped)] if kept else [_footer(dropped)]
        parts = build_messages(
            category.title, body, slots, cfg.tiers, cfg.round_to_nearest,
            price_format=cfg.price_format,
        )

    return parts, dropped


async def publish_category(
    api: BotApi,
    cfg: Config,
    category: Category,
    slot: CategorySlot,
) -> bool:
    """Обновить или создать сообщения одной категории. True, если что-то изменилось."""
    parts, dropped = render_category(category, slot, cfg)
    empty = sum(1 for part in parts if "\n" not in part)
    if empty:
        log.warning(
            "Категория '%s': %d сообщений останутся пустыми — в источнике стало меньше позиций",
            category.title, empty,
        )
    if dropped:
        log.warning(
            "Категория '%s': контент не влез в %d сообщений, скрыто %d позиций "
            "(включите allow_create, чтобы бот добавил сообщения)",
            category.title, len(slot.message_ids), dropped,
        )

    keyboard = _order_keyboard(cfg)
    new_hash = content_hash(parts + [repr(keyboard)])
    if slot.content_hash == new_hash and len(slot.message_ids) >= len(parts):
        log.info("Категория '%s' без изменений", category.title)
        return False

    changed = False

    for index, text in enumerate(parts):
        if index < len(slot.message_ids):
            message_id = slot.message_ids[index]
            result = await api.edit_message_text(
                cfg.target_chat_id, message_id, text, reply_markup=keyboard,
            )
            if result is None:
                log.warning(
                    "Не удалось отредактировать '%s' часть %d (message_id=%d)",
                    category.title, index + 1, message_id,
                )
                return False
            if result is not NOT_MODIFIED:
                changed = True
            log.info("Обновлено: '%s' часть %d/%d", category.title, index + 1, len(parts))
            await asyncio.sleep(EDIT_DELAY_SECONDS)
        elif cfg.allow_create:
            result = await api.send_message(
                cfg.target_chat_id, text,
                disable_notification=cfg.disable_notification,
                reply_markup=keyboard,
            )
            if result is None:
                log.warning("Не удалось создать сообщение для '%s'", category.title)
                return changed
            slot.message_ids.append(int(result["message_id"]))
            changed = True
            log.info(
                "Создано: '%s' часть %d/%d (message_id=%s)",
                category.title, index + 1, len(parts), result["message_id"],
            )
            await asyncio.sleep(CREATE_DELAY_SECONDS)
        else:
            log.warning(
                "Для '%s' не хватает сообщений, а allow_create выключен", category.title,
            )
            break

    slot.content_hash = new_hash
    return changed


def build_excel(
    cfg: Config,
    state: State,
    categories: dict[str, Category],
) -> tuple[bytes, str, list] | None:
    """Собрать книгу .xlsx и записать её в excel.output_dir.

    Возвращает (байты, имя файла, позиции) или None, если выгрузка выключена
    либо позиций нет.
    """
    if not cfg.excel_enabled:
        return None

    ordered = [categories[key] for key in planned_keys(cfg, state) if key in categories]
    rows = collect_rows(ordered, cfg.tiers, cfg.round_to_nearest)
    if not rows:
        log.warning("Нет позиций для выгрузки в Excel")
        return None

    payload = build_workbook(rows)
    filename = build_filename(cfg.excel_filename)

    cfg.excel_output_dir.mkdir(parents=True, exist_ok=True)
    path = cfg.excel_output_dir / filename
    path.write_bytes(payload)
    log.info("Excel-прайс сохранён: %s (%d позиций, %d КБ)", path, len(rows), len(payload) // 1024)

    return payload, filename, rows


async def publish_excel(
    api: BotApi,
    cfg: Config,
    state: State,
    categories: dict[str, Category],
) -> bool:
    """Собрать .xlsx и, если включена публикация, залить его в канал."""
    built = build_excel(cfg, state, categories)
    if built is None:
        return False

    payload, filename, rows = built
    if not cfg.excel_publish:
        return False

    new_hash = rows_hash(rows)
    if state.excel_message_id and state.excel_hash == new_hash:
        log.info("Excel-прайс в канале без изменений (%d позиций)", len(rows))
        return False

    caption = build_caption(rows)

    if state.excel_message_id:
        result = await api.edit_message_document(
            cfg.target_chat_id, state.excel_message_id, filename, payload, caption=caption,
        )
        if result is None:
            log.warning("Не удалось обновить Excel-прайс (message_id=%s)", state.excel_message_id)
            return False
        state.excel_hash = new_hash
        log.info("Excel-прайс в канале обновлён: %d позиций", len(rows))
        return True

    result = await api.send_document(
        cfg.target_chat_id, filename, payload,
        caption=caption, disable_notification=cfg.disable_notification,
    )
    if result is None:
        log.warning("Не удалось загрузить Excel-прайс")
        return False

    state.excel_message_id = int(result["message_id"])
    state.excel_hash = new_hash
    log.info(
        "Excel-прайс загружен в канал: %d позиций (message_id=%s)",
        len(rows), state.excel_message_id,
    )
    return True


def read_info_text(cfg: Config) -> str | None:
    """Прочитать текст информационного сообщения; None — если выключено или пусто."""
    if not cfg.info_enabled:
        return None
    try:
        text = cfg.info_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        log.error("Не удалось прочитать %s: %s", cfg.info_file, exc)
        return None
    if not text:
        log.warning("Файл %s пуст — информационное сообщение пропущено", cfg.info_file)
        return None
    if len(text) > TELEGRAM_MAX_LEN:
        log.error(
            "Информационное сообщение длиннее %d символов (%d) — Telegram его не примет",
            TELEGRAM_MAX_LEN, len(text),
        )
        return None
    return text


async def publish_info(api: BotApi, cfg: Config, state: State) -> bool:
    """Создать или обновить информационное сообщение перед навигацией."""
    text = read_info_text(cfg)
    if text is None:
        return False

    new_hash = content_hash([text])
    if state.info_message_id and state.info_hash == new_hash:
        log.info("Информационное сообщение без изменений")
        return False

    if state.info_message_id:
        result = await api.edit_message_text(cfg.target_chat_id, state.info_message_id, text)
        if result is None:
            log.warning(
                "Не удалось обновить информационное сообщение (message_id=%s)",
                state.info_message_id,
            )
            return False
        state.info_hash = new_hash
        log.info("Информационное сообщение обновлено (message_id=%s)", state.info_message_id)
        return True

    result = await api.send_message(
        cfg.target_chat_id, text, disable_notification=cfg.disable_notification,
    )
    if result is None:
        log.warning("Не удалось создать информационное сообщение")
        return False

    state.info_message_id = int(result["message_id"])
    state.info_hash = new_hash
    log.info("Информационное сообщение создано (message_id=%s)", state.info_message_id)
    return True


async def ensure_nav_is_last(api: BotApi, cfg: Config, state: State) -> bool:
    """Навигация должна быть последним сообщением канала.

    Сообщения нельзя переставлять, поэтому если информационное оказалось ниже
    навигации, старую навигацию удаляем — publish_nav создаст её заново внизу.
    """
    if not (state.nav_message_id and state.info_message_id):
        return False
    if state.nav_message_id > state.info_message_id:
        return False

    if await api.delete_message(cfg.target_chat_id, state.nav_message_id) is None:
        log.warning(
            "Не удалось удалить старую навигацию (message_id=%s) — порядок сообщений "
            "останется прежним", state.nav_message_id,
        )
        return False

    log.info("Старая навигация удалена, будет пересоздана ниже информационного сообщения")
    state.nav_message_id = None
    state.nav_hash = None
    return True


async def publish_nav(api: BotApi, cfg: Config, state: State) -> bool:
    """Создать или обновить навигационное сообщение с кнопками."""
    if not cfg.nav_enabled:
        return False

    entries: list[tuple[str, str]] = []
    for key in planned_keys(cfg, state):
        slot = state.slots.get(key)
        if not slot or not slot.message_ids:
            continue
        entries.append(
            (slot.title, message_link(cfg.target_chat_id, cfg.target_channel, slot.message_ids[0]))
        )

    if not entries:
        log.warning("Нет опубликованных категорий — навигация пропущена")
        return False

    extra = []
    if cfg.order_button is not None:
        extra.append([
            make_button(cfg.order_button.text, cfg.order_button.url, cfg.order_button.style)
        ])
    if cfg.excel_enabled and cfg.excel_publish and state.excel_message_id:
        extra.append([make_button(
            cfg.excel_button_text,
            message_link(cfg.target_chat_id, cfg.target_channel, state.excel_message_id),
            cfg.excel_button_style,
        )])

    keyboard = build_keyboard(
        entries, cfg.nav_columns, extra, cfg.nav_button_style, cfg.nav_row_width,
    )
    text = render_text(cfg.nav_text)
    new_hash = content_hash([text, repr(keyboard)])

    if state.nav_message_id and state.nav_hash == new_hash:
        log.info("Навигация без изменений")
        return False

    if state.nav_message_id:
        result = await api.edit_message_text(
            cfg.target_chat_id, state.nav_message_id, text, reply_markup=keyboard,
        )
        if result is None:
            log.warning("Не удалось обновить навигацию (message_id=%s)", state.nav_message_id)
            return False
        state.nav_hash = new_hash
        log.info("Навигация обновлена (message_id=%s)", state.nav_message_id)
        return True

    result = await api.send_message(
        cfg.target_chat_id, text,
        disable_notification=cfg.disable_notification,
        reply_markup=keyboard,
    )
    if result is None:
        log.warning("Не удалось создать навигацию")
        return False

    state.nav_message_id = int(result["message_id"])
    state.nav_hash = new_hash
    log.info("Навигация создана (message_id=%s)", state.nav_message_id)

    if cfg.nav_pin:
        if await api.pin_message(cfg.target_chat_id, state.nav_message_id) is None:
            log.warning("Закрепить навигацию не удалось — сделайте это вручную")
    return True


async def sync_once(
    api: BotApi,
    session: aiohttp.ClientSession,
    cfg: Config,
    state: State,
    *,
    state_path: Path,
) -> None:
    """Один цикл синхронизации всех запланированных категорий."""
    categories = await fetch_source_categories(session, cfg)
    if not categories:
        log.error("В канале-источнике @%s не найдено ни одной категории", cfg.source_channel)
        return

    keys = planned_keys(cfg, state)
    if not keys:
        log.error("Список категорий пуст: задайте 'categories' в config.yaml или запустите --seed")
        return

    missing = [key for key in keys if key not in categories]
    if missing:
        log.warning("Нет в источнике (пропускаю): %s", ", ".join(missing))

    todo = [key for key in keys if key in categories]
    log.info("Синхронизирую %d категорий", len(todo))

    for key in todo:
        category = categories[key]
        slot = state.slots.setdefault(key, CategorySlot(title=category.title))
        slot.title = category.title
        try:
            if await publish_category(api, cfg, category, slot):
                save_state(state, state_path)
        except Exception:
            log.exception("Сбой на категории '%s'", category.title)

    try:
        if await publish_excel(api, cfg, state, categories):
            save_state(state, state_path)
    except Exception:
        log.exception("Сбой при выгрузке Excel")

    try:
        if await publish_info(api, cfg, state):
            save_state(state, state_path)
        if await ensure_nav_is_last(api, cfg, state):
            save_state(state, state_path)
    except Exception:
        log.exception("Сбой при публикации информационного сообщения")

    try:
        await publish_nav(api, cfg, state)
    except Exception:
        log.exception("Сбой при публикации навигации")

    save_state(state, state_path)


def dry_run(cfg: Config, categories: dict[str, Category], state: State, out_dir: Path) -> None:
    """Собрать сообщения без публикации и разложить их по файлам для проверки."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for key in planned_keys(cfg, state):
        if key not in categories:
            continue
        category = categories[key]
        slot = state.slots.get(key) or CategorySlot(title=category.title)
        parts, dropped = render_category(category, slot, cfg)
        safe = category.title.replace("/", "_").replace("\\", "_").strip()
        for index, text in enumerate(parts, start=1):
            (out_dir / f"{safe}.{index}.txt").write_text(text, encoding="utf-8")
        log.info(
            "%s: %d позиций -> %d сообщений (слотов %d, скрыто %d)",
            category.title, count_price_lines(category.lines), len(parts),
            len(slot.message_ids), dropped,
        )
