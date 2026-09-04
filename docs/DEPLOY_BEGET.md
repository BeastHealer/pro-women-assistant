# Развёртывание на VPS Beget

Инструкция для стека `pro-women-assistant` + sibling `tg_vk_parser` на VPS Beget
(Ubuntu + Docker Compose). Официальные материалы Beget:

- [Виртуальные серверы (VPS/VDS)](https://beget.com/ru/kb/manual/virtual-servers)
- [Первые шаги после создания VPS](https://beget.com/ru/kb/how-to/vps/sozdaniya-vps-nastrojka-i-monitoring)
- [Docker через Portainer](https://beget.com/ru/kb/how-to/vps/kak-rabotat-s-docker-cherez-portainer)
- [Видео: UFW на Ubuntu](https://beget.com/ru/kb/how-to/vps/video-ustanovka-i-nastroyka-fayrvola-v-ubuntu-s-pomoshchyu-utility-ufw)

---

## Рекомендуемые параметры VPS

| Параметр | Минимум | Комфортно |
|----------|---------|-----------|
| ОС | Ubuntu 22.04 / 24.04 LTS | то же |
| RAM | 4 GB | **8 GB** (CLIP/torch в `parser-api`) |
| CPU | 2 vCPU | 4 vCPU |
| Диск | 40 GB SSD | 80+ GB (фотоархив) |
| Образ | чистая Ubuntu **или** маркетплейс [Docker](https://beget.com/ru/kb/manual/virtual-servers) | Docker / Portainer |

Маркетплейс Beget умеет ставить готовые образы Docker, n8n, Portainer — для нашего
монорепо с кастомным `build context` удобнее **Docker + CLI** (`docker compose`),
а Portainer — опционально для мониторинга.

---

## 1. Создать VPS в панели Beget

1. Панель → **Облако / VPS** → создать сервер.
2. Выберите регион, тариф (≥ 4 GB RAM), ОС Ubuntu 24.04 **или** образ **Docker**.
3. Добавьте **SSH-ключ** (ed25519) на этапе создания — см. [первые шаги](https://beget.com/ru/kb/how-to/vps/sozdaniya-vps-nastrojka-i-monitoring).
4. В панели включите **брандмауэр VPS**: разрешите `22`, `80`, `443` (и временно ничего больше).
5. Привяжите домен: DNS A-записи
   - `YOUR_DOMAIN` → IP VPS  
   - `n8n.YOUR_DOMAIN` → тот же IP  

Пароль root приходит на почту аккаунта; дальше лучше только ключ.

```bash
ssh root@IP_СЕРВЕРА
```

---

## 2. Bootstrap (Docker, UFW, пользователь)

Скрипт ставит официальный Docker Engine + Compose plugin, UFW, пользователя `deployer`:

```bash
# скопируйте репозиторий или только scripts на сервер, затем:
bash scripts/beget/01-bootstrap.sh
```

Вручную то же самое описано в Beget (SSH, ключи, firewall) + установка Docker с
[docs.docker.com](https://docs.docker.com/engine/install/ubuntu/).

**Важно:** Docker может обходить UFW при публикации `0.0.0.0:port`. В нашем
`docker-compose.yml` порты assistant/parser/n8n привязаны к `127.0.0.1`; наружу
смотрят только `80/443` у nginx.

Дублируйте правила и в **брандмауэре панели Beget**, и в UFW.

---

## 3. Загрузить код и данные

На сервере под `deployer`:

```bash
su - deployer
mkdir -p ~/workspace && cd ~/workspace
```

С локальной машины (PowerShell / scp):

```powershell
scp -r .\pro-women-assistant deployer@IP:~/workspace/
scp -r .\tg_vk_parser deployer@IP:~/workspace/
```

Или `git clone` обоих репозиториев **рядом**:

```text
~/workspace/
  pro-women-assistant/
  tg_vk_parser/          # data/images.db, approved_images/, …
```

Проверка:

```bash
ls ~/workspace/tg_vk_parser/data/images.db
```

---

## 4. Секреты и nginx

```bash
cd ~/workspace/pro-women-assistant
cp .env.production.example .env
nano .env
```

Обязательно:

- все `VK_*`, `GIGACHAT_*`, `YONOTE_*` (включая `YONOTE_DB_REPORTS_PROPS`);
- `SENLER_*`, `N8N_PASSWORD`;
- `WEBHOOK_URL=https://n8n.YOUR_DOMAIN`;
- `PARSER_API_URL=http://parser-api:8000`.

Статус отчётов в Yonote select: **`новый`** (как в коде `/webhook` и `/generate/digest`).

Подставьте домен в nginx:

```bash
export DOMAIN=your-domain.ru
sed -i "s/YOUR_DOMAIN/${DOMAIN}/g" nginx/nginx.prod.conf
```

### TLS (Let's Encrypt)

Пока certs нет — сначала поднимите стек на HTTP (временно правьте `nginx.prod.conf`
на `listen 80` only) **или** получите сертификаты на хосте:

```bash
sudo apt install -y certbot
sudo certbot certonly --standalone -d YOUR_DOMAIN -d n8n.YOUR_DOMAIN
sudo mkdir -p ~/workspace/pro-women-assistant/nginx/certs
sudo cp /etc/letsencrypt/live/YOUR_DOMAIN/fullchain.pem nginx/certs/
sudo cp /etc/letsencrypt/live/YOUR_DOMAIN/privkey.pem nginx/certs/
sudo chown -R deployer:deployer nginx/certs
```

`certbot --standalone` требует свободные 80/443 (остановите nginx на время выпуска).

---

## 5. Сборка и запуск

```bash
cd ~/workspace/pro-women-assistant
bash scripts/beget/02-deploy.sh
# или:
# DOMAIN=your-domain.ru bash scripts/beget/02-deploy.sh
```

Эквивалент:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile with-nginx up -d --build
```

Проверка:

```bash
bash scripts/beget/04-healthcheck.sh
curl -fsS https://YOUR_DOMAIN/health
curl -fsS https://n8n.YOUR_DOMAIN/healthz
```

CLIP-индекс архива (долго, один раз):

```bash
curl -X POST 'http://127.0.0.1:8000/admin/rebuild-index?batch_size=4'
```

---

## 6. Senler и n8n

1. Откройте `https://n8n.YOUR_DOMAIN` (логин `admin` / `N8N_PASSWORD`).
2. Webhook Senler: `https://n8n.YOUR_DOMAIN/webhook/senler-report` → proxy на
   `http://assistant:8080/webhook/senler/report` с заголовком `X-Senler-Secret`.
3. Weekly digest: Schedule → `POST http://assistant:8080/generate/digest`.

В `.env` на сервере: `WEBHOOK_URL=https://n8n.YOUR_DOMAIN`.

---

## 7. Бэкапы и мониторинг

Cron от `deployer`:

```bash
crontab -e
```

```cron
*/5 * * * * /home/deployer/workspace/pro-women-assistant/scripts/beget/04-healthcheck.sh >> /home/deployer/logs/health.log 2>&1
0 3 * * * /home/deployer/workspace/pro-women-assistant/scripts/beget/03-backup.sh >> /home/deployer/logs/backup.log 2>&1
```

Нагрузку смотрите также в панели Beget → **Статистика нагрузки**
([первые шаги](https://beget.com/ru/kb/how-to/vps/sozdaniya-vps-nastrojka-i-monitoring)).

---

## 8. Обновление

```bash
cd ~/workspace/pro-women-assistant
# git pull / scp новых файлов
bash scripts/beget/02-deploy.sh
```

---

## 9. Типичные проблемы на Beget

| Симптом | Что сделать |
|---------|-------------|
| Порт открыт в UFW, но снаружи закрыт | Проверьте **брандмауэр в панели** Beget |
| Сервис доступен с интернета на :8080 | Не должен: только `127.0.0.1`; пересоберите с `docker-compose.prod.yml` |
| OOM / parser падает | Мало RAM для torch — тариф ≥ 8 GB или отложите rebuild-index |
| Senler webhook не доходит | `WEBHOOK_URL`, DNS `n8n.`, TLS, basic auth n8n |
| `database.rows.list` 400 UUID | В `.env` UUID БД, не URL-slug (клиент умеет резолвить, но лучше UUID) |

---

## Файлы в репозитории

| Путь | Назначение |
|------|------------|
| `docker-compose.yml` | Базовый стек (порты на localhost) |
| `docker-compose.prod.yml` | Логи, nginx prod conf, n8n secure cookie |
| `nginx/nginx.prod.conf` | HTTPS + subdomains |
| `scripts/beget/01-bootstrap.sh` | Docker + UFW + deployer |
| `scripts/beget/02-deploy.sh` | build/up |
| `scripts/beget/03-backup.sh` | SQLite + n8n export |
| `scripts/beget/04-healthcheck.sh` | локальный health |
| `.env.production.example` | шаблон секретов для VPS |
