# Контент-ассистент PRO Женщин Москва — техническая документация

> Публичное описание для неспециалистов: [../README.md](../README.md).

ИИ-пайплайн для еженедельных дайджестов, приёма отчётов малых групп (Senler),
черновиков в yonote.ru, утверждения в закрытой группе ВК и подбора фото из
архива `tg_vk_parser` (CLIP + FAISS).

Публикации в открытую группу — только после human-in-the-loop.

---

## Стек

| Слой | Технологии |
|------|------------|
| API | Python 3.11+, FastAPI, uvicorn, httpx |
| LLM | GigaChat (`gigachat` SDK) |
| Соцсети | VK API, Senler webhooks |
| Черновики / БД отчётов | yonote.ru API |
| Оркестрация | n8n (self-hosted) |
| Фотоархив | sibling `tg_vk_parser` → SQLite `pipeline_images` + CLIP/FAISS |
| Контейнеры | Docker Compose (`docker-compose.yml` в корне этого репо) |

---

## Структура репозитория

```text
pro-women-assistant/
├── assistant/           # FastAPI: webhooks, /generate/digest, /approve
├── content/
│   ├── generator.py     # вызовы GigaChat
│   └── prompts/         # ← промпты и стиль ЖИВУТ ЗДЕСЬ (не в yonote)
│       ├── system_prompt.txt   # системный промпт (роль, правила, пайплайн)
│       ├── style_guide.txt     # стилистический гайд бренда
│       └── digest.md           # шаблон задачи дайджеста ({reports_json}, {photos_context})
├── giga/                # клиент и конфиг GigaChat
├── vk/                  # публикация / опросы
├── yonote/              # Documents + Database API
├── parser_api/          # FastAPI-обёртка над архивом фото (CLIP/FAISS)
├── nginx/               # опциональный reverse-proxy (--profile with-nginx)
├── n8n/                 # место для экспорта workflow (пока заготовка)
├── tests/
├── docker-compose.yml   # n8n + parser-api + assistant (+ nginx)
├── .env.example
├── requirements.txt     # зависимости assistant
└── cursorrules          # соглашения для Cursor
```

Ожидаемый workspace (для Docker volume):

```text
SMM-asistant/
├── pro-women-assistant/   # этот проект
└── tg_vk_parser/          # data/images.db, approved фото, индексы
```

---

## Промпты и стиль (важно)

| Файл | Назначение |
|------|------------|
| `content/prompts/system_prompt.txt` | Системный промпт ИИ: роль ассистента, human-in-the-loop, контекст сообщества, ограничения |
| `content/prompts/style_guide.txt` | Стилистический гайд (тон, «так / не так», бренд) |
| `content/prompts/digest.md` | User-шаблон задачи «еженедельный дайджест» |

Эти файлы редактируются в git. **Не** храните гайд как документ yonote и **не** задавайте `YONOTE_DOC_STYLE_GUIDE` — переменная устарела и не нужна.

yonote.ru используется для:

- Database отчётов малых групп (`YONOTE_DB_REPORTS` = id документа типа database);
- коллекции черновиков Documents (`YONOTE_COLLECTION_DRAFTS`).

API (см. [developers](https://yonote.ru/developers?v=1)): Documents/Collections — RPC
`documents.*` / `collections.list`; строки БД — `database.rows.list` и
`database/transaction`.  
Для записи отчётов задайте `YONOTE_DB_REPORTS_PROPS` (JSON: имя колонки → UUID свойства).

Пошаговая настройка workspace — в разделе [Настройка инфраструктуры в Yonote](#настройка-инфраструктуры-в-yonote).

---

## Настройка инфраструктуры в Yonote

Цель: завести в [app.yonote.ru](https://app.yonote.ru) минимальный контур, с которым работает ассистент
(отчёты Senler → Database, дайджест → Documents «Черновики»).  
Справочник API: [yonote.ru/developers](https://yonote.ru/developers?v=1). Продуктовая справка: [yonote.ru/docs](https://yonote.ru/docs).

### 0. Что должно получиться

```text
Рабочее пространство PRO Women (или ваш project)
├── Коллекция «Контент» (или аналог)
│   ├── База данных «Отчёты малых групп»     → YONOTE_DB_REPORTS
│   └── (опционально) БД «Статусы дайджестов»
└── Коллекция «Черновики»                    → YONOTE_COLLECTION_DRAFTS
```

Промпты и стилистический гайд **не** создаём в Yonote — они в `content/prompts/`.

### 1. Аккаунт, пространство и API-токен

1. Зарегистрируйтесь / войдите на [app.yonote.ru](https://app.yonote.ru).
2. Создайте или откройте рабочее пространство команды (если у вас свой поддомен —
   base URL будет вида `https://{project}.yonote.ru/api`).
3. Перейдите в **Настройки → API** (или «API-токены» / сервисный аккаунт — в зависимости от тарифа).
4. Создайте токен с правами **чтения и записи** на нужные коллекции (документы + базы данных).
5. Скопируйте токен в `.env`:

```env
YONOTE_API_KEY=скопированный_токен
YONOTE_BASE_URL=https://app.yonote.ru/api
# если свой project:
# YONOTE_BASE_URL=https://ваш-проект.yonote.ru/api
```

Токен действует от имени пользователя/бота, который его создал: выдайте этому
аккаунту доступ редактора на коллекции из шага 2–3.

### 2. Коллекция «Черновики»

1. В боковой панели: **Новая коллекция** → название `Черновики` (или `Контент / Черновики`).
2. Права: команда РП / контент — **редактирование**; API-бот — **редактирование**.
3. Скопируйте UUID коллекции:
   - из URL вида `.../collection/{uuid}` или `.../collections/{uuid}`;
   - либо через API: `POST /api/collections.list` с Bearer-токеном и найдите коллекцию по `name`.
4. В `.env`:

```env
YONOTE_COLLECTION_DRAFTS=uuid_коллекции_Черновики
```

Сюда ассистент кладёт документы дайджестов (`documents.create` с `collectionId`).

### 3. База данных «Отчёты малых групп»

1. В подходящей коллекции (например «Контент») создайте **новую базу данных**
   (тип документа *database*), название: `Отчёты малых групп`.
2. Добавьте колонки (имена в UI могут быть по-русски; в `.env` важны **UUID свойств**,
   логические ключи слева — как в коде ассистента):

| Логический ключ (для `.env`) | Рекомендуемое имя в UI | Тип колонки | Пример / примечание |
|------------------------------|------------------------|-------------|---------------------|
| `group_name` | Название группы | text | «Ольга_Висцералка» |
| `meeting_date` | Дата встречи | text или date | `2026-08-10` |
| `participants_count` | Число участниц | number | `8` |
| `theme` | Тема | text | тема встречи |
| `insights` | Инсайты | text | длинный текст |
| `status` | Статус | select | стартовое значение `новый` |
| `created_at` | Создано | text или date | ISO-дата от webhook |

Допустимые значения `status` (как в БД / коде MVP):

- `новый` — только что пришёл отчёт (фильтр в `/generate/digest`);
- `на проверке` / `проверено` / `отложенная публикация` / `опубликовано` — дальше по процессу.

3. Скопируйте UUID **самого документа-базы** (не коллекции):
   - из URL открытой БД;
   - это значение `parentDocumentId` для `database.rows.list` / ключ в `database/transaction`.
4. Опционально скопируйте UUID **коллекции**, в которой лежит БД (некоторые операции row
   ожидают `collectionId`):

```env
YONOTE_DB_REPORTS=uuid_документа_базы_Отчёты
YONOTE_DB_REPORTS_COLLECTION=uuid_коллекции_где_лежит_БД
```

### 4. Карта колонок `YONOTE_DB_REPORTS_PROPS`

API пишет и фильтрует строки по **id свойств**, а не по русским названиям.
Нужно сопоставить логические ключи кода с id колонок (`propertyConfig` в `documents.info`).

**Способ A — из UI**  
Откройте настройки колонки / «свойства базы» и скопируйте id свойства, если интерфейс его показывает.

**Способ B — через API** (надёжнее). В **PowerShell** `curl` — это alias `Invoke-WebRequest`,
поэтому используйте `curl.exe` или Python:

```powershell
# Вариант 1: curl.exe (не путать с curl = Invoke-WebRequest)
curl.exe -X POST "$env:YONOTE_BASE_URL/documents.info" `
  -H "Authorization: Bearer $env:YONOTE_API_KEY" `
  -H "Content-Type: application/json" `
  -d "{\"id\": \"$env:YONOTE_DB_REPORTS\"}"

# Вариант 2: из корня проекта, значения берутся из .env
python -c "from pathlib import Path; import json; from dotenv import dotenv_values; import httpx; d=dotenv_values('.env'); b=d.get('YONOTE_BASE_URL','https://app.yonote.ru/api').rstrip('/'); h={'Authorization':'Bearer '+d['YONOTE_API_KEY'],'Content-Type':'application/json'}; doc=httpx.post(b+'/documents.info',json={'id':d['YONOTE_DB_REPORTS'].split('?')[0]},headers=h,timeout=30).json()['data']; print('UUID', doc['id']); cfg=doc.get('propertyConfig') or {};
[print(f\"{v.get('title')}: {k} ({v.get('type')})\") for k,v in cfg.items() if isinstance(v, dict)]"
```

В ответе смотрите `propertyConfig`: у каждого поля `id` и `title`.  
Колонка «название группы» часто имеет id=`title` (заголовок строки) — в карте пишите `"group_name":"title"`.

Пример заполнения `.env` (подставьте свои UUID из вывода выше):

```env
YONOTE_DB_REPORTS=a9a82694-26b6-4a29-909e-e42b9642e75a
YONOTE_DB_REPORTS_PROPS={"group_name":"title","meeting_date":"6538cb38-e372-45ed-84d5-71aeda0b42bb","participants_count":"6fc0bd8b-953a-41ef-8ed2-da8ad2cd650d","theme":"bae2c65f-df2f-40dd-80fd-eae923efc6cc","insights":"595b3997-089c-4d6b-a274-b38d68d613fe","status":"323ac82e-9246-4d1c-9caa-526788443f8d","created_at":"e0bd4a2e-bb2d-47d8-9948-11f0bdd10f4d"}
```

Статус в select БД должен совпадать с кодом. Сейчас ассистент пишет и ищет
`новый`.

Без этой карты webhook может создать строку, но ячейки останутся пустыми.

### 5. (Опционально) База «Статусы дайджестов» и База знаний

В `system_prompt.txt` заложен расширенный контур. Для MVP **не обязателен**, но удобен команде:

| Объект | Назначение | Когда понадобится |
|--------|------------|-------------------|
| БД «Статусы дайджестов» | черновик → на утверждении → доработать / отклонено / опубликовано | автоматизация статусов HITL |
| Коллекция / документы «База знаний» | FAQ, регламенты для ответов ассистента | сценарий FAQ / модерации |
| Коллекция «Архив» | перенос опубликованных черновиков | вместо/вместе с `documents.archive` |

Пока код использует только **Отчёты** + **Черновики**; остальные сущности можно завести заранее
и подключить в следующих итерациях.

### 6. Права доступа (чек-лист)

- [ ] Аккаунт API-токена видит коллекцию «Черновики» (create/update/archive документов).
- [ ] Тот же аккаунт видит БД «Отчёты» (rows.list + transaction).
- [ ] Участники контент-команды могут править черновики в UI (human-in-the-loop).
- [ ] Токен не закоммичен в git (только `.env` / secrets CI).

### 7. Проверка, что инфраструктура жива

Из корня проекта (с заполненным `.env`):

```bash
# Список коллекций — должны увидеть «Черновики»
python -m pytest tests/test_yonote.py -v -s

# Или вручную:
curl -X POST "https://app.yonote.ru/api/collections.list" ^
  -H "Authorization: Bearer YOUR_TOKEN" ^
  -H "Content-Type: application/json" ^
  -d "{}"
```

Тест записи отчёта (после старта assistant):

```bash
curl -X POST http://localhost:8080/webhook/senler/report ^
  -H "Content-Type: application/json" ^
  -H "X-Senler-Secret: ваш_SENLER_WEBHOOK_SECRET" ^
  -d "{\"user_id\":1,\"group_name\":\"Тест\",\"meeting_date\":\"2026-08-13\",\"participants_count\":5,\"theme\":\"Пилот\",\"insights\":\"Проверка yonote\"}"
```

В UI БД «Отчёты» должна появиться строка со статусом `новый`.  
Затем:

```bash
curl -X POST http://localhost:8080/generate/digest
```

В коллекции «Черновики» — новый документ с текстом дайджеста.

### 8. Типичные ошибки

| Симптом | Что проверить |
|---------|----------------|
| `401` / Unauthenticated | `YONOTE_API_KEY`, не протух ли токен |
| `403` / Unauthorized | права аккаунта токена на коллекцию/БД |
| `404` на rows.list | `YONOTE_DB_REPORTS` — id **документа-БД**, не коллекции |
| `400 parentDocumentId must be a UUID` | В `.env` попал URL/slug (`...-yJ44...?v=...`). Клиент умеет резолвить slug→UUID; лучше сразу поставить UUID из `documents.info` |
| Строка есть, колонки пустые | не заполнен или неверный `YONOTE_DB_REPORTS_PROPS` |
| Дайджест «Нет данных» | нет строк со `status=новый` или filter/props не совпали |
| Документ не в «Черновиках» | неверный `YONOTE_COLLECTION_DRAFTS` |

---

## Правила разработки

- Type hints обязательны; docstrings в Google style.
- Логирование через `logging`; секреты только в `.env`.
- Асинхронный I/O где возможно (`asyncio`, `httpx`).
- Именование: `snake_case` / `PascalCase` / `UPPER_SNAKE_CASE`; URL — kebab-case.
- Тексты для аудитории: дружественно-профессиональный тон с оттенком вдохновения (см. гайд).

---

## Быстрый старт

### 1. Окружение

```bash
cd pro-women-assistant
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# Linux/macOS
# source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
# заполните секреты в .env
```

Тесты:

```bash
# Windows: команда pytest часто не в PATH — используйте модуль:
python -m pip install -r requirements.txt
python -m pytest tests/ -v
python -m pytest tests/test_yonote.py -v -s
python -m pytest tests/test_giga.py -v -s
```

### 2. Переменные окружения

Полный список с комментариями — в [`.env.example`](.env.example). Кратко:

| Группа | Переменные | Зачем |
|--------|------------|--------|
| VK | `VK_ACCESS_TOKEN`, `VK_*_GROUP_ID`, … | Черновик в закрытой / пост в открытой |
| GigaChat | `GIGACHAT_CREDENTIALS`, модели, scope | Генерация текстов |
| yonote | `YONOTE_API_KEY`, `YONOTE_COLLECTION_DRAFTS`, `YONOTE_DB_REPORTS`, `YONOTE_DB_REPORTS_PROPS` | Черновики + Database rows (**без** style guide) |
| Senler | `SENLER_WEBHOOK_SECRET`, `SENLER_API_TOKEN` | Приём отчётов |
| Parser | `PARSER_API_URL`, пути к БД/индексу | Поиск фото |
| n8n | `N8N_PASSWORD`, `WEBHOOK_URL` | Оркестрация |

Локально для assistant укажите:

```env
PARSER_API_URL=http://localhost:8000
```

В Docker Compose для сервиса `assistant` уже выставляется `PARSER_API_URL=http://parser-api:8000`.

### 3. Локальный запуск Parser API

Нужен sibling `../tg_vk_parser` с `data/images.db` (таблица `pipeline_images`).

```bash
cd parser_api
pip install -r requirements.txt

# Windows (пример абсолютных путей)
set PARSER_DB_PATH=F:\PROWOMEN_Backup\SMM-asistant\tg_vk_parser\data\images.db
set TG_VK_PARSER_ROOT=F:\PROWOMEN_Backup\SMM-asistant\tg_vk_parser
python main.py
```

Swagger: http://localhost:8000/docs

Проверки:

```bash
curl "http://localhost:8000/health"
# ожидайте: status=ok, table=pipeline_images, approved_photos>0

curl "http://localhost:8000/stats"
curl "http://localhost:8000/search?q=%D0%B2%D1%81%D1%82%D1%80%D0%B5%D1%87%D0%B0&limit=3"
# mode=text_fallback пока нет FAISS-индекса архива

# Сборка CLIP-индекса (долго, CPU/GPU + диск):
curl -X POST "http://localhost:8000/admin/rebuild-index?batch_size=4"
# после этого /health → archive_index=ready, /search → mode=clip_faiss
```

Эндпоинты parser_api:

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/health` | БД + наличие archive index |
| GET | `/search?q=&limit=` | CLIP+FAISS или LIKE-fallback |
| GET | `/latest` | Последние approved |
| GET | `/stats` | Статусы / авторы / диапазон дат |
| POST | `/admin/rebuild-index` | Пересборка `archive_index.faiss` |
| GET | `/photo/{id}/image` | Файл фото |

Индекс архива (`archive_index.faiss` + `archive_metadata.json`) **отдельный** от эталонного `reference_index.faiss` в UI парсера.

### 4. Локальный запуск Assistant

В другом терминале (из корня `pro-women-assistant`, с активированным venv и `.env`):

```bash
set PARSER_API_URL=http://localhost:8000
# или: $env:PARSER_API_URL="http://localhost:8000"
python -m uvicorn assistant.main:app --host 0.0.0.0 --port 8080
# либо: cd assistant && python main.py
```

Swagger: http://localhost:8080/docs

```bash
curl http://localhost:8080/health
curl -X POST http://localhost:8080/generate/digest
```

Эндпоинты assistant (текущий MVP):

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/health` | Liveness |
| POST | `/webhook/senler/report` | Отчёт малой группы → yonote Database |
| POST | `/generate/digest` | Отчёты + фото из parser → GigaChat → yonote + VK closed |
| POST | `/approve/{doc_id}` | Публикация в открытую группу + архив документа |
| GET | `/stats` | Токены GigaChat / метка времени |

> Маршрут `/classify/comment` описан в планах n8n, но в API пока не выставлен (логика есть в `ContentGenerator.classify_comment`).

---

## Docker Compose

Из корня `pro-women-assistant` (рядом должен быть `../tg_vk_parser`):

```bash
cp .env.example .env   # если ещё нет
docker compose up -d --build
docker compose ps
docker compose logs -f parser-api
```

Сервисы:

| Контейнер | Порт | Роль |
|-----------|------|------|
| `pro-women-n8n` | 5678 | Оркестрация |
| `pro-women-parser` | 8000 | Поиск по фотоархиву |
| `pro-women-assistant` | 8080 | Контент API |
| `pro-women-nginx` | 80/443 | Только с `--profile with-nginx` |

```bash
# опционально reverse-proxy
docker compose --profile with-nginx up -d

# после первого старта — индекс архива
curl -X POST "http://localhost:8000/admin/rebuild-index?batch_size=4"
```

Устаревший файл `assistant/docker-compose.yml` — заглушка; используйте корневой `docker-compose.yml`.

---

## Развёртывание на VPS (Beget)

Пошаговая инструкция для Beget (создание VPS, SSH-ключи, брандмауэр панели + UFW,
Docker, TLS, скрипты): **[docs/DEPLOY_BEGET.md](docs/DEPLOY_BEGET.md)**.

Кратко:

```bash
# на VPS (root)
bash scripts/beget/01-bootstrap.sh

# deployer: код + sibling tg_vk_parser в ~/workspace/
cd ~/workspace/pro-women-assistant
cp .env.production.example .env   # заполнить секреты
export DOMAIN=your-domain.ru
sed -i "s/YOUR_DOMAIN/${DOMAIN}/g" nginx/nginx.prod.conf
# положить TLS в nginx/certs/
bash scripts/beget/02-deploy.sh
bash scripts/beget/04-healthcheck.sh
```

Публично: `https://YOUR_DOMAIN` (assistant), `https://n8n.YOUR_DOMAIN` (n8n).  
Сервисы `:8080/:8000/:5678` слушают только `127.0.0.1`.

Официальные гайды Beget: [первые шаги VPS](https://beget.com/ru/kb/how-to/vps/sozdaniya-vps-nastrojka-i-monitoring),
[Docker / Portainer](https://beget.com/ru/kb/how-to/vps/kak-rabotat-s-docker-cherez-portainer),
[обзор VPS](https://beget.com/ru/kb/manual/virtual-servers).

---

## n8n (черновик workflow)

Импорт готовых JSON из `n8n/` пока может отсутствовать — создайте вручную.

### Weekly Digest

1. **Schedule Trigger** — cron `0 6 * * 1`, TZ `Europe/Moscow`
2. **HTTP Request** — `POST http://assistant:8080/generate/digest`
3. **IF** — `{{$json.status}} === "success"` → уведомление команде / ошибка

### Senler → Assistant

1. **Webhook** `POST` path `senler-report`  
   URL для Senler: `https://your-domain/webhook/senler-report` (или `:5678/webhook/...`)
2. **HTTP Request** → `POST http://assistant:8080/webhook/senler/report`  
   Header: `X-Senler-Secret` = значение из `.env`
3. **Respond to Webhook** — `{"status":"ok"}`

### Модерация комментариев (план)

Расписание каждые 30 мин → VK `wall.get` / комментарии → (когда появится) `POST /classify/comment` → удалить SPAM / эскалировать SUSPICIOUS.

---

## Senler (сценарий отчёта)

Сценарий «Сбор отчёта малой группы»: название группы, дата, число участниц, тема, инсайты, опционально фото → webhook на n8n.

Напоминание лидерам (вс 18:00) — отдельный сценарий/сегмент «без отчёта за неделю».

---

## Чек-лист тестирования

### Локально

- [ ] `pytest tests/ -v`
- [ ] Parser `/health` → `pipeline_images`, `approved_photos > 0`
- [ ] После rebuild → `archive_index=ready`, `/search` → `clip_faiss`
- [ ] Assistant `/health` → `ok`
- [ ] Промпты читаются с диска: `content/prompts/*.txt|md`

### E2E

- [ ] Senler → n8n → `/webhook/senler/report` → строка в yonote Database
- [ ] `/generate/digest` создаёт черновик и пост в закрытой группе
- [ ] `/approve/{doc_id}` публикует в открытую и архивирует документ
- [ ] При недоступности parser — дайджест всё же генерируется (без фото)
- [ ] При недоступности yonote — ошибки логируются, есть fallback-ветки

---

## Мониторинг и бэкапы (рекомендации)

Минимальный health-check каждые 5 минут: `8080/health`, `8000/health`, `5678/healthz`.

Бэкапить:

- `../tg_vk_parser/data/images.db`
- экспорт workflow n8n: `docker exec pro-women-n8n n8n export:workflow --all --pretty`

HTTPS: certbot + файлы в `nginx/certs/`, затем `docker compose --profile with-nginx up -d`.

---

## Известные ограничения MVP

1. Публикация фото в VK пока передаёт локальные `file_path` — нужна загрузка через VK Photos API.
2. Опрос утверждения может уходить текстом вместо нативного `poll` attachment.
3. Каталоги `senler/`, `n8n/workflow/` — заготовки; деплой-скрипты — в `scripts/beget/`.
4. `ContentGenerator` собирает system message из `system_prompt.txt` + `style_guide.txt` (для модерации комментариев — только system prompt).

---

## Полезные ссылки внутри репо

- [Настройка инфраструктуры в Yonote](#настройка-инфраструктуры-в-yonote)
- [Развёртывание на Beget](docs/DEPLOY_BEGET.md)
- [`.env.example`](.env.example) · [`.env.production.example`](.env.production.example)
- [`yonote/client.py`](yonote/client.py) — Documents + Database API v1
- [`content/prompts/system_prompt.txt`](content/prompts/system_prompt.txt)
- [`content/prompts/style_guide.txt`](content/prompts/style_guide.txt)
- [`docker-compose.yml`](docker-compose.yml) · [`docker-compose.prod.yml`](docker-compose.prod.yml)
- Sibling: `../tg_vk_parser/README.md` — фильтрация архива, Streamlit UI, эталоны CLIP
- Внешние: [yonote.ru/developers](https://yonote.ru/developers?v=1) · [yonote.ru/docs](https://yonote.ru/docs) · [Beget VPS](https://beget.com/ru/kb/manual/virtual-servers)
