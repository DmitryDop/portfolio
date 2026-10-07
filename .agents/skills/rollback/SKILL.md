---
name: rollback
description: Безопасный rollback portfolio к подтверждённой production-версии.
---

# Rollback

Работай из корня проекта. Прочитай `AGENTS.md`, `docs/production-protocol.md`
и `.agents/skills/deploy/SKILL.md`: snapshot, exclusions и verification общие.
Production: `https://dopler.lineband.ru/`; SSH: `lineba`;
remote path: `/home/l/linebaru/dopler/public_html/`.

## Target

1. Проверь Git status, ветку, HEAD, изменения, оба SHA-файла и history.json.
   Выполни `python3 scripts/production.py inspect`.
2. Current/previous достоверны только при согласованной истории подтверждённых событий загрузки или baseline-наблюдения,
   существующих commits и manifest/evidence по общему протоколу.
3. Сравни current manifest с фактическими SHA-256 на сервере и HTTP.
   При расхождении остановись. История не доказывает отсутствие ручных изменений.
4. Target — previous валидной истории, отличный от current. Покажи полные SHA,
   messages, event ids и diff production-файлов.
5. После первого deploy previous пуст: подтверждённого target нет.
   Не выбирай HEAD~1 или SHA без evidence. Git history только для поиска кандидатов:
   нужны проверяемые журналы успешной загрузки, не подтверждение задним числом.
6. Повреждённая история, legacy SHA без evidence, отсутствующий commit или
   рассогласование зеркал требуют остановки, а не автоматического fallback.

## Подготовка и разрешение

Зафиксируй полный TARGET_SHA до загрузки. Подготовь отдельный snapshot через
production.py prepare; проверь ссылки, secrets, manifest и неизменность snapshot.
Не загружай рабочую копию и не переключай/reset рабочую ветку.
Выполни checksum dry-run `-rvzcn --itemize-changes` с общими exclusions.
Покажи target, evidence, changed files, dry-run, exclusions и remote path.

Rollback изменяет production: по AGENTS.md для реального rsync нужна отдельная
явная команда `DEPLOY` применительно к показанному rollback-плану. Обхода проверок
нет. Запрос rollback или симуляции сам по себе загрузку не разрешает.
Повторно проверь metadata, current и snapshot; удали только `n` из согласованной
команды. Никаких автоматических `--delete`, reset/clean или переписывания истории.

Покажи managed-файлы current, отсутствующие в target. Если они влияют на поведение,
остановись до отдельного разрешения необходимых удалений по точным paths.
Не объявляй rollback полным при несовместимых оставшихся файлах.
Не трогай `.well-known/`, `.htaccess`, secrets и неизвестные серверные файлы.

## Verification и metadata

Проверь SHA-256 всех target managed-файлов на сервере, HTTP 200 и SHA-256 тел URL,
главную страницу, защищённые файлы и разрешённые удаления по общему протоколу.
Только после успешной verification добавь событие operation=rollback через transition;
commit обязан совпадать с подтверждённым previous до операции.
Новый current = target, previous = прежний подтверждённый current.
При любой ошибке остановись и сообщи этап и возможное частичное состояние production.
Не выполняй автоматический обратный rollback. Ошибка записи/sync metadata не повод
повторять rsync. Commit/push только с отдельным разрешением.
После всех проверок покажи восстановленные файлы, удаления, event id,
current/previous, HTTP/SHA-256 verification и `ROLLBACK: SUCCESS`.


## Совместимость с baseline

Baseline A подтверждает наблюдаемое содержимое A, а не успех исторического rsync.
Один baseline имеет previous пусто: rollback target ещё нет. После успешного deploy B
с live verification A target становится A. Baseline evidence допустим как основание
известности target, но не вместо post-upload evidence самого rollback.
Перед rollback A собери новое observation B и передай live_current в transition;
после успешной загрузки и verification A запись даёт A/B. Не создавай baseline
в существующей истории и не обходи отключённую adoption API. Подробности —
раздел baseline в docs/production-protocol.md; локальные тесты — docs/production-testing.md.
