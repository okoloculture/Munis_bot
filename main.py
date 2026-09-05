"""Точка входа: сидирование карты категорий, разовый прогон и периодическая синхронизация."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

import aiohttp

from bot_api import BotApi
from config import Config, ConfigError, load_config
from state import DEFAULT_STATE_PATH, load_state, save_state
from sync import (
    build_excel,
    discover_slots,
    dry_run,
    fetch_source_categories,
    is_allowed,
    planned_keys,
    sync_once,
)

log = logging.getLogger("munis_bot")


def _make_session(cfg: Config) -> aiohttp.ClientSession:
    """Сессия aiohttp; SOCKS-прокси подключается через коннектор."""
    proxy = cfg.proxy
    if proxy and proxy.startswith("socks5h://"):
        proxy = "socks5://" + proxy[len("socks5h://"):]
    if proxy and proxy.startswith(("socks4://", "socks5://")):
        from aiohttp_socks import ProxyConnector

        return aiohttp.ClientSession(connector=ProxyConnector.from_url(proxy, rdns=True))
    return aiohttp.ClientSession()


async def run_seed(cfg: Config, state_path: Path) -> None:
    """Построить карту «категория -> сообщения» по текущему содержимому целевого канала."""
    async with _make_session(cfg) as session:
        discovered = await discover_slots(session, cfg)

    if not discovered:
        log.error("В канале @%s не найдено постов-прайсов (заголовок '📦 ...')", cfg.target_channel)
        return

    state = load_state(state_path)
    for key, slot in discovered.items():
        existing = state.slots.get(key)
        if existing and existing.message_ids == slot.message_ids:
            continue
        slot.content_hash = None
        state.slots[key] = slot

    stale = [key for key in state.slots if key not in discovered]
    for key in stale:
        log.warning("Категория '%s' пропала из канала — удаляю из карты", state.slots[key].title)
        del state.slots[key]

    save_state(state, state_path)
    log.info("Карта сохранена: %d категорий", len(state.slots))
    for key, slot in sorted(state.slots.items()):
        mark = "" if is_allowed(key, cfg) else "  [исключена конфигом]"
        log.info("  %-28s -> %s%s", slot.title, slot.message_ids, mark)


async def run_dry_run(cfg: Config, state_path: Path, out_dir: Path) -> None:
    """Собрать сообщения и записать в файлы, ничего не публикуя."""
    state = load_state(state_path)
    if not planned_keys(cfg, state):
        log.error("Список категорий пуст: задайте 'categories' в config.yaml или запустите --seed")
        return

    async with _make_session(cfg) as session:
        categories = await fetch_source_categories(session, cfg)

    dry_run(cfg, categories, state, out_dir)
    log.info("Результат записан в %s", out_dir)


async def run_excel(cfg: Config, state_path: Path) -> None:
    """Собрать только файл .xlsx, не трогая канал."""
    if not cfg.excel_enabled:
        log.error("Выгрузка выключена: включите 'excel.enabled' в config.yaml")
        return

    state = load_state(state_path)
    async with _make_session(cfg) as session:
        categories = await fetch_source_categories(session, cfg)

    if build_excel(cfg, state, categories) is None:
        log.error("Файл не собран")


async def run_sync(cfg: Config, state_path: Path, *, once: bool) -> None:
    """Синхронизировать один раз или в бесконечном цикле."""
    state = load_state(state_path)

    async with _make_session(cfg) as session:
        api = BotApi(
            session,
            cfg.bot_token,
            http_proxy=cfg.proxy if cfg.proxy and cfg.proxy.startswith("http") else None,
        )
        me = await api.get_me()
        if me is None:
            log.error("Bot API недоступен или токен неверен")
            return
        log.info("Бот @%s готов", me.get("username"))

        await sync_once(api, session, cfg, state, state_path=state_path)
        if once:
            return

        log.info("Периодическая синхронизация каждые %d с. Ctrl+C для остановки.", cfg.check_interval)
        while True:
            await asyncio.sleep(cfg.check_interval)
            try:
                await sync_once(api, session, cfg, state, state_path=state_path)
            except Exception:
                log.exception("Сбой цикла синхронизации")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Зеркалирование прайсов с наценкой")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--seed", action="store_true", help="построить карту категорий по целевому каналу")
    mode.add_argument("--dry-run", action="store_true", help="собрать сообщения в файлы без публикации")
    mode.add_argument("--once", action="store_true", help="один прогон синхронизации и выход")
    mode.add_argument("--excel", action="store_true", help="собрать только файл .xlsx, не трогая канал")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--out", type=Path, default=Path("_dryrun"), help="каталог для --dry-run")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        cfg = load_config(
            args.config, require_token=not (args.seed or args.dry_run or args.excel),
        )
    except ConfigError as exc:
        log.error("Конфигурация: %s", exc)
        return 1

    if args.seed:
        asyncio.run(run_seed(cfg, args.state))
    elif args.dry_run:
        asyncio.run(run_dry_run(cfg, args.state, args.out))
    elif args.excel:
        asyncio.run(run_excel(cfg, args.state))
    else:
        asyncio.run(run_sync(cfg, args.state, once=args.once))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
