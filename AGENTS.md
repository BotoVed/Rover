# Release procedure

## Prerequisites

- PAT with `repo` scope in `.env` as `GITHUB_TOKEN`
- `hacs.json` already has `zip_release: true` and `filename: "rover.zip"`
- Local git is clean, committed, and pushed to `main`

## Подключение к HAOS

Хост для тестирования — Home Assistant OS (192.168.1.114, порт 222).

```bash
sshpass -p '$HAOS_PASS' ssh -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null -p $HAOS_PORT \
  $HAOS_USER@$HAOS_HOST "<command>"
```

Креды в `.env`:
```
HAOS_HOST=192.168.1.114
HAOS_PORT=222
HAOS_USER=root
HAOS_PASS=775Ho
```

Типичные команды:
- `ls -la /config/custom_components/rover/` — проверить файлы интеграции
- `ha core logs | grep -i rover` — логи HA по rover
- `ha core restart` — перезагрузить HA
- `cat /config/custom_components/rover/manifest.json` — версия интеграции

## Создание релиза (для HACS)

При каждом повышении минорной версии (`x.y.0 → x.(y+1).0`) или при необходимости обновить HACS-пакет:

### 1. Обновить версии

В трёх местах должна быть одинаковая версия:
- `custom_components/rover/__init__.py`: `__version__ = "X.Y.Z"`
- `custom_components/rover/manifest.json`: `"version": "X.Y.Z"`
- `pyproject.toml`: `version = "X.Y.Z"`

### 2. Закоммитить и запушить

```bash
cd tmp/rover
git add -A
git commit -m "back vX.Y.Z — description"
git push origin main
```

### 3. Собрать rover.zip

ZIP должен содержать файлы в корне (без `rover/`-префикса), иначе HACS распакует с двойной вложенностью.

```bash
cd tmp/rover/custom_components/rover
zip -r ../../rover.zip . -x "__pycache__/*" "*.pyc"
cd ../..
```

Проверка содержимого:

```bash
unzip -l rover.zip | head -30
```

Должен содержать файлы в корне:
```
__init__.py
manifest.json
const.py
codec.py
config_flow.py
options_flow.py
brand/icon.png
translations/en.json
...
```

### 4. Создать тег (чистый semver, БЕЗ префикса)

```bash
git tag X.Y.Z
git push origin X.Y.Z
```

⚠️ Тег ДОЛЖЕН быть чистым semver: `0.2.0`, `1.0.0` — НЕ `back-0.2.0`, НЕ `v0.2.0`. HACS парсит теги как semver и игнорирует нестандартные форматы.

### 5. Создать GitHub Release через API

```bash
# Создать Release
RESPONSE=$(curl -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/BotoVed/Rover/releases \
  -d '{
    "tag_name": "X.Y.Z",
    "name": "vX.Y.Z — description",
    "body": "Release notes here",
    "draft": false,
    "prerelease": false
  }')

# Извлечь upload_url
UPLOAD_URL=$(echo "$RESPONSE" | grep '"upload_url"' | sed 's/.*"upload_url": "//;s/{.*//')
```

### 6. Прикрепить rover.zip к Release

```bash
curl -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Content-Type: application/zip" \
  "${UPLOAD_URL}?name=rover.zip" \
  --data-binary @rover.zip
```

### 7. Убрать временный ZIP

```bash
rm rover.zip
```

### 8. Проверить

- https://github.com/BotoVed/Rover/releases — видим релиз с прикреплённым `rover.zip`.
- В HACS: удалить и заново добавить `BotoVed/Rover` → при установке выбрать версию → должно скачаться без ошибок.
- На HAOS: `ls -la /config/custom_components/rover/` — файлы без двойной вложенности.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| HACS 404 / download as `1df2c31.zip` | Release tag name doesn't match `manifest.json` version | Create release with tag matching `version` field exactly |
| Files in `rover/rover/` (double nesting) | ZIP built with `rover/` prefix | Rebuild from inside `custom_components/rover/` — files flat |
| `No module named 'rover'` | Absolute imports `from rover.xxx` | Use relative imports `from .xxx` |
| `RequirementsNotFound: meshtastic==X.Y.Z` | PyPI version missing or download failed | Bump to existing version; check HACS download first |