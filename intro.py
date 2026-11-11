"""Вводные посты канала: приветствие, знакомство, как заказать.

Стоят в самом начале канала, перед прайсами, и открывают навигацию отдельными
кнопками. Каждый пост — rich-сообщение: фото сверху и текст из HTML-файла.
Текст и фото лежат в репозитории (каталог intro/), бот правит пост только
когда они меняются.

Подпись к фото у бота ограничена 1024 символами, а тексты длиннее, поэтому
пост собирается как rich-сообщение: у него лимит 32768 символов.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from catalog import normalize_key

# Ключ в state.slots; префикс не даёт вводному посту совпасть с категорией опта.
INTRO_KEY_PREFIX = "intro: "
# Идентификатор фото внутри rich-сообщения: <img src="tg://photo?id=photo"/>.
PHOTO_ID = "photo"


class IntroConfigError(ValueError):
    """Вводный пост задан некорректно."""


@dataclass(frozen=True)
class IntroPost:
    """Вводный пост: подпись кнопки, файл с текстом и необязательное фото."""

    title: str
    html_file: Path
    photo_file: Path | None = None

    @property
    def key(self) -> str:
        return INTRO_KEY_PREFIX + normalize_key(self.title)


def parse_intro_posts(raw: object) -> tuple[IntroPost, ...]:
    """Разобрать intro_posts: [{title, html, photo?}, …]; файлы должны существовать."""
    if not raw:
        return ()
    if not isinstance(raw, list):
        raise IntroConfigError("'intro_posts' должен быть списком {title, html, photo}")

    posts = []
    for item in raw:
        title = item.get("title") if isinstance(item, dict) else None
        html_file = item.get("html") if isinstance(item, dict) else None
        if not isinstance(title, str) or not title.strip():
            raise IntroConfigError("У вводного поста нужен непустой 'title'")
        if not isinstance(html_file, str) or not Path(html_file).is_file():
            raise IntroConfigError(f"Вводный пост '{title}': файл с текстом не найден: {html_file}")
        photo = item.get("photo")
        if photo is not None and not Path(str(photo)).is_file():
            raise IntroConfigError(f"Вводный пост '{title}': фото не найдено: {photo}")
        posts.append(IntroPost(
            title=title.strip(),
            html_file=Path(html_file),
            photo_file=Path(str(photo)) if photo else None,
        ))
    return tuple(posts)


def load_intro(post: IntroPost) -> tuple[str, dict[str, bytes] | None, str]:
    """Прочитать пост: (HTML rich-сообщения, фото для загрузки, хеш содержимого)."""
    body = post.html_file.read_text(encoding="utf-8").strip()
    digest = hashlib.md5(body.encode("utf-8"))
    if post.photo_file is None:
        return body, None, digest.hexdigest()

    photo = post.photo_file.read_bytes()
    digest.update(photo)
    html_text = f'<img src="tg://photo?id={PHOTO_ID}"/>\n{body}'
    return html_text, {PHOTO_ID: photo}, digest.hexdigest()
