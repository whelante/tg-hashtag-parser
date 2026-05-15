# TG Hashtag Parser

Парсер публичных Telegram-каналов по хэштегам с admin-ботом.

## Структура

```
tg_parser/
├── main.py          ← точка входа
├── database.py      ← SQLite (WAL, lock, одно соединение)
├── parser.py        ← Telethon MTProto парсер
├── bot.py           ← admin-бот с inline кнопками
├── filters.py       ← фильтрация спама и сигналов
├── requirements.txt
├── .env.example
└── data/            ← создаётся автоматически
    ├── posts.db     ← база данных
    ├── parser.session  ← сессия пользователя
    └── bot.session     ← сессия бота
```

## Запуск

```bash
pip install -r requirements.txt
cp .env.example .env   # заполнить 4 значения
python main.py
```

При первом запуске введи номер телефона и код из Telegram.
При следующих запусках логин не нужен — сессия сохранена в `data/parser.session`.

## Команды бота

| Команда | Действие |
|---|---|
| `/add_tag #BTC` | Добавить хэштег |
| `/remove_tag #BTC` | Убрать хэштег |
| `/list_tags` | Список всех тегов |
| `/run_search` | Запустить поиск |
| `/stats` | Статистика |
| `/status` | Состояние парсера |

## Inline кнопки

Каждый найденный пост приходит с кнопками:
- ✅ Publish → статус `published`
- 🚫 Spam → статус `spam`  
- ❌ Bad source → статус `bad_source`
- ⏭ Skip → статус `skipped`

## .env

```
API_ID=        ← my.telegram.org
API_HASH=      ← my.telegram.org
BOT_TOKEN=     ← @BotFather
ADMIN_USER_ID= ← @userinfobot
```
