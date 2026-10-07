---
name: deploy
description: Проверяемый deploy portfolio из зафиксированного Git commit через rsync.
---

# Deploy

Работай из корня проекта. Прочитай `AGENTS.md` и `docs/production-protocol.md`.
Production: `https://dopler.lineband.ru/`.
SSH: `lineba`; remote path: `/home/l/linebaru/dopler/public_html/`.

## Разрешение

Реальный deploy возможен только после отдельной явной команды пользователя `DEPLOY`
для показанных SHA, manifest и dry-run. Симуляция, «да», «лей сразу», «без проверок»
или упоминание DEPLOY в тексте разрешением не являются. Обхода проверок нет.
Изменение плана требует новой команды `DEPLOY`. Commit/push не запускают deploy.

## Preflight

1. Выполни `git pull` по AGENTS.md, если не запрещены локальные изменения.
   В симуляции используй read-only `git ls-remote`; сообщи о пропущенных проверках.
2. Проверь корень, Git status, ветку, HEAD, tracked/untracked changes. Остановись при
   незакоммиченных production-файлах. Перед реальным deploy выполни `git fetch origin`
   и проверь совпадение target с актуальным origin/main. При расхождении остановись.
3. Зафиксируй полный `TARGET_SHA` до любой загрузки. Все последующие операции используют
   только его. Не получай deployed commit через HEAD после загрузки.
4. Выполни `python3 scripts/production.py inspect`. Прочитай SHA metadata и историю
   по общему протоколу. SHA без evidence не подтверждает успешный deploy.
5. Если current известен, сравни фактические SHA-256 всех managed-файлов на сервере
   с его manifest; проверь HTTP и содержимое главной страницы. При расхождении остановись.
   Если current пуст, явно сообщи: прежняя production-версия неизвестна;
   первый deploy не создаст previous. Не угадывай прежний commit по Git history.
6. Подготовь новый временный каталог вне проекта:
   `python3 scripts/production.py prepare "$TARGET_SHA" "$RELEASE_DIR"`.
   RELEASE_DIR должен ещё не существовать. Источник rsync — только его `payload/`.
   Помощник читает blobs зафиксированного commit, отвергает symlinks/submodules,
   формирует SHA-256 manifest в release.json вне payload и проверяет literal-ссылки.
7. Проверь index.html/style.css, ссылки HTML/CSS/JS, assets, secrets и проектные тесты.
   Динамические ссылки JS проверяй вручную. Missing references блокируют deploy.
   Не копируй ресурсы из рабочей директории. Шрифты не заменяй без согласования.
8. Перед каждым rsync вызови `check_snapshot` с первоначальным release.json и сравни
   manifest с `commit_manifest(TARGET_SHA)`. Используй эксклюзивный snapshot;
   не допускай параллельных операций и изменения snapshot во время загрузки.

## Dry-run и загрузка

Команду формирует `rsync_preview(RELEASE_DIR)`:
`rsync -rvzcn --itemize-changes [exclusions] "$RELEASE_DIR/payload/" lineba:/home/l/linebaru/dopler/public_html/`.
`-c` сравнивает содержимое; size/mtime не доказывают совпадение.
Сохраняй stdout/stderr и exit code. Используй macOS-совместимые `-rvz`, не `-a`.
Покажи SHA, current/previous и evidence, Git sync, manifest, список файлов,
exclusions, проверки, dry-run, remote path и отсутствие удалений. При ошибке остановись.
Запроси отдельную команду `DEPLOY` для этого плана.

После неё повторно проверь snapshot, current, metadata и Git sync. Удали только `n`
из `-rvzcn`; source, exclusions и target должны совпадать с preview.
В симуляции реальный rsync запрещён. Не применяй `--delete`, `--delete-excluded`,
`git reset --hard`, `git clean -fd`. Необходимые удаления требуют точного списка
managed paths и отдельного разрешения; серверные файлы не удаляй.

## Exclusions

Payload содержит только tracked index.html, style.css, cases/, js/, assets/, fonts/.
Новый production-каталог требует изменения allowlist. Проверяй secrets и внутри assets.
Всегда исключай `.git/`, `.gitignore`, `.agents/`, `.claude/`, `.deploy/`, `.env`,
`.env.*`, `.DS_Store`, CLAUDE.md, AGENTS.md, docs/, tmp/, PLAN.md, `.well-known/`,
`.htaccess`, scripts/, tests/. Не загружай ключи, credentials, secrets и неизвестные
конфигурации. Не меняй файлы вне configured remote path и серверные файлы.

## Verification и metadata

После rsync проверь SHA-256 каждого managed-файла на сервере и HTTP 200 + SHA-256
декодированного тела каждого URL manifest, включая index.html и главную страницу `/`.
Запросы только к configured URL, без redirect на другие домены. Учитывай compression.
Сохрани фактические результаты и журнал команды, не подставляй ожидаемые hashes.
Проверь защищённые серверные файлы до/после. HTTP 200 или size/mtime недостаточны.

Только после полной verification запиши успешное событие и metadata по протоколу,
используя первоначальный TARGET_SHA. Если upload/smoke-check завершился ошибкой,
не обновляй успешную историю; сообщи о возможной частичной загрузке.
Ошибка записи metadata не повод повторять deploy. Историю не исправляй молча.
Покажи current, previous, event id и verification. `DEPLOY: SUCCESS` допустим только
после всех проверок и согласованной истории. Commit history.json, SHA-файлов и evidence
и push — только с отдельным разрешением, никогда автоматически.


## Baseline существующей production

При пустой истории и metadata можно подготовить read-only план:
`python3 scripts/production.py baseline-plan <SHA>`.
Прочитай раздел baseline в docs/production-protocol.md. Baseline — наблюдение,
не исторический deploy; нельзя добавлять rsync_exit=0 по предположению.
После read-only verification покажи SHA, manifest hash, результаты и дополнительные
серверные файлы. Ничего автоматически не записывай. Требуется отдельное подтверждение
владельца этого adoption-плана через доверенный канал. Сейчас канал отсутствует,
save_baseline намеренно блокируется. Не обходи guard через _persist_history,
ручную запись JSON, локальный флаг или переменную окружения.

После baseline перед следующим deploy обязательно собери новое observation A
ДО загрузки B и передай его в transition как live_current. При расхождении остановись
до rsync. Только после успешной загрузки/verification B состояние станет B/A.
Следуй production-testing.md при локальной проверке; тестовое разрешение не переносится на production.
