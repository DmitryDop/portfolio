---
name: rollback
description: Безопасный откат production-версии portfolio на предыдущую рабочую версию. Используй этот Skill при запросах на rollback, откат, возврат предыдущей версии или восстановление production после неудачного деплоя.
---

# Rollback

## Purpose

Безопасно вернуть production portfolio к предыдущей известной рабочей версии.

Пользователь всегда принимает финальное решение.

---

## Environment

Server (SSH alias):

`lineba`

Remote path:

`/home/l/linebaru/dopler/public_html`

Production URL:

`https://dopler.lineband.ru/`

Deployment tool:

`rsync`

Работай только из корневой папки проекта.

---

# Rollback source

По умолчанию источником rollback является Git.

Перед откатом определи:

- текущий production commit, если он известен;
- текущий локальный commit;
- предыдущий production commit;
- какие production-файлы отличаются между текущей и предыдущей версиями.

Никогда не выбирай commit для rollback наугад.

Если невозможно надёжно определить предыдущую рабочую версию — остановись и спроси пользователя.

---

## Production version metadata

Перед анализом Git history сначала проверь:

`.deploy/production-current`

и

`.deploy/production-previous`

Используй их как основной источник информации о production-версиях.

Правила:

1. Если `.deploy/production-current` содержит commit:
   - считай его текущей известной production-версией.
2. Если `.deploy/production-previous` содержит commit:
   - считай его основным кандидатом для rollback.
3. Проверь, что оба commit существуют в Git.
4. Покажи:
   - current production commit;
   - previous production commit;
   - commit messages;
   - различия между ними.
5. Не доверяй metadata вслепую:
   - если commit отсутствует в Git;
   - если файл повреждён;
   - если значения некорректны;
   - если metadata противоречит текущему состоянию,
   остановись и сообщи пользователю.

Если `.deploy/production-current` или `.deploy/production-previous` пусты, отсутствуют или не позволяют надёжно определить rollback target — используй Git history как fallback и спроси пользователя при неоднозначности.

Не изменяй `.deploy/production-current` и `.deploy/production-previous` до успешного завершения rollback.

---

# SAFE ROLLBACK — режим по умолчанию

Если пользователь пишет:

- `rollback`
- `откати`
- `верни прошлую версию`
- `откати прод`
- `верни предыдущий деплой`

выполняй SAFE ROLLBACK.

## Before rollback

1. Проверь `git status`.
2. Покажи:
   - текущую ветку;
   - текущий commit;
   - uncommitted changes;
   - untracked files.
3. Определи commit, на который предлагается rollback.
4. Покажи:
   - current production commit;
   - rollback target commit;
   - commit message;
   - список production-файлов, которые изменятся.
5. Проверь, что rollback target существует в Git.
6. Не изменяй рабочую ветку пользователя без необходимости.
7. Не выполняй `git reset --hard` автоматически.
8. Не переписывай историю Git.
9. Подготовь содержимое rollback target отдельно от текущей рабочей копии, если это возможно.
10. Исключи служебные и серверные файлы теми же правилами, что и при deploy.
11. Выполни dry-run будущей загрузки на production.
12. Не выполняй реальный rollback на этом этапе.

После подготовки покажи краткий отчёт:

- current production commit;
- rollback target;
- changed files;
- dry-run result;
- deployment target;
- будут ли требоваться удаления;
- найденные риски.

После этого спроси:

`Продолжить rollback?`

До явного подтверждения production не изменять.

---

# BOSS OVERRIDE

Пользователь может явно приказать немедленный rollback.

Примеры:

- `откатывай сразу`
- `верни прошлую версию немедленно`
- `rollback now`
- `катись назад без проверок`

В этом режиме:

1. Не спорь с пользователем.
2. Пропусти обычные quality checks, если пользователь явно этого требует.
3. Не требуй дополнительного подтверждения.
4. Всё равно определи конкретный rollback target.
5. Никогда не выбирай commit наугад.
6. Не изменяй служебные, серверные или приватные файлы.
7. Не используй destructive Git commands без необходимости.
8. Не используй `--delete`, если пользователь явно не разрешил удаление.

Если rollback target нельзя определить однозначно — остановись и спроси пользователя даже при Boss override.

---

# Critical safety rules

Никогда автоматически:

- не выполняй `git reset --hard`;
- не выполняй `git clean -fd`;
- не переписывай историю;
- не удаляй production-файлы без необходимости;
- не загружай `.env`;
- не загружай SSH keys;
- не загружай secrets;
- не загружай `.git/`;
- не загружай `.agents/`;
- не загружай `.claude/`;
- не загружай `.deploy/`;
- не загружай `.gitignore`;
- не загружай `AGENTS.md`;
- не загружай `CLAUDE.md`;
- не загружай `.DS_Store`;
- не изменяй `.well-known/`;
- не изменяй `.htaccess`;
- не изменяй неизвестные серверные файлы, не относящиеся к tracked production-файлам portfolio.

Rollback должен затрагивать только production HTML, CSS, JS и assets, необходимые для возврата версии.

---

# Files excluded from rollback upload

Всегда исключай как минимум:

- `.git/`
- `.gitignore`
- `.agents/`
- `.claude/`
- `.deploy/`
- `.env`
- `.env.*`
- `.DS_Store`
- `CLAUDE.md`
- `AGENTS.md`
- `docs/`
- `tmp/`
- `PLAN.md`
- `.well-known/`
- `.htaccess`

Также не загружай:

- SSH private keys;
- credentials;
- API keys;
- локальные конфигурационные файлы с секретами;
- любые файлы, явно не предназначенные для production.

---

# Rollback procedure

Предпочтительный способ:

1. Определи rollback target commit.
2. Подготовь содержимое этого commit отдельно.
3. Не переключай текущую рабочую ветку пользователя, если можно этого избежать.
4. Выполни `rsync` dry-run с теми же exclusions, что используются при deploy.
5. Покажи изменения.
6. После подтверждения выполни реальный `rsync`.
7. Не используй `--delete` без явного разрешения.

Если для корректного rollback требуется удаление файлов, появившихся только в новой версии:

1. покажи точный список таких файлов;
2. объясни, почему без удаления rollback будет неполным;
3. запроси отдельное подтверждение на удаление.

Boss override не считается автоматическим разрешением на удаление файлов, если пользователь прямо этого не сказал.

---

# Server-side files protection

Portfolio — статический сайт. Обычный rollback должен восстанавливать только файлы сайта из Git.

Не изменяй автоматически файлы, которые обслуживаются сервером или хостингом отдельно от Git, включая:

- `.well-known/`;
- `.htaccess`;
- сертификаты;
- hosting/service configuration;
- приватные серверные файлы;
- неизвестные файлы, происхождение которых не установлено.

Если не уверен, относится ли файл к portfolio — не трогай его автоматически.

---

# Post-rollback verification

После rollback обязательно проверь:

1. HTTP status `https://dopler.lineband.ru/`;
2. что главная страница отдаётся;
3. что `index.html` соответствует rollback-версии;
4. страницы кейсов или assets, которые были затронуты rollback;
5. что `.well-known/`, `.htaccess` и другие защищённые серверные файлы не были изменены;
6. что production не содержит случайно загруженных локальных служебных файлов.

---

# Production metadata after successful rollback

После успешного rollback и успешного smoke-check:

1. Сохрани production commit, который был активен до rollback.
2. Запиши rollback target commit в:

`.deploy/production-current`

3. Предыдущий production commit до rollback запиши в:

`.deploy/production-previous`

4. Создай отдельный commit:

`Record production rollback <short-commit>`

5. Выполни `git push`.

Не включай в этот commit посторонние изменения.

Если Git sync metadata завершился ошибкой:

- rollback всё равно считается выполненным;
- сообщи об ошибке синхронизации;
- не запускай rollback повторно.

---

# Rollback report

После завершения сообщи:

- rollback target commit;
- какие файлы были восстановлены;
- какие файлы не трогались;
- были ли удаления;
- smoke-check result;
- HTTP status;
- warnings.

Если rollback прошёл успешно, явно сообщи:

`ROLLBACK: SUCCESS`

Если verification не пройдена, не сообщай об успешном rollback.

---

# Failure handling

Если любой этап завершается ошибкой:

1. останови дальнейшие действия;
2. сообщи точный этап;
3. покажи ошибку;
4. не продолжай destructive actions;
5. не скрывай проблему;
6. не пытайся молча чинить production.

Если rollback сам создаёт новую проблему — остановись и сообщи пользователю текущее состояние production.
