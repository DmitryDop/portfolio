# Проверка безопасности deploy и rollback

Дата: 2026-10-08, Europe/Moscow.
Исходный commit: `77ad1e569ca152eee27dc55432a8d7c01f7c23ba`.
Режим: только локальные изменения и тесты; production не запрашивался и не изменялся.

## Изученная архитектура и изменения

Проект — статический сайт без существующего тестового runner или executable deploy
скрипта. Процесс описывался двумя deploy skills и одним rollback skill. Два SHA-файла
существовали пустыми; подтверждающей истории не было. Сохранены rsync, параметры
совместимости macOS, SSH alias, remote path, HTTPS URL, исключения, защита серверных
файлов и запрет автоматических удалений.

Изменены:

- `.agents/skills/deploy/SKILL.md`: pinned SHA, snapshot, preflight, checksum dry-run,
  content verification, запись подтверждённой истории и разрешение только `DEPLOY`.
- `.agents/skills/rollback/SKILL.md`: target только из подтверждённой истории,
  тот же snapshot/verification и согласованный переход metadata.
- `.claude/skills/deploy/SKILL.md`: ссылка на единый актуальный протокол вместо
  расходящейся копии с HTTP URL и неполными exclusions.
- `AGENTS.md`, `CLAUDE.md`: согласованные правила разрешения и проверки содержимого.

Добавлены:

- `scripts/production.py`: локальные prepare/check/inspect; SHA-256 manifest;
  валидация evidence и цепочки; чистые переходы; запись журнала через lock,
  проверку исходных bytes, fsync и atomic rename отдельных файлов.
- `tests/test_production.py`: 29 изолированных локальных тестов, включая четыре CSS-регрессии.
- `docs/production-protocol.md`: schema, evidence, первый/repeat deploy,
  rollback, legacy metadata и восстановление после неполной записи.
- Этот отчёт.

Сайт, CSS, JS, assets, fonts и реальные production metadata не изменены.
История успешных production deploy не создавалась: для этого не было фактической
загрузки и verification. Synthetic evidence применяется только в временных тестовых repos.

## PASS / FAIL по требованиям

| № | Проверка | Результат | Основание |
| --- | --- | --- | --- |
| 1 | SHA фиксируется до загрузки | PASS | Resolve выполняется один раз; дальнейшие чтения используют полный SHA |
| 2 | Файлы именно зафиксированного commit | PASS | Git blobs → отдельный payload; изменения HEAD/worktree и untracked не попадают в snapshot |
| 3 | Проверка прежнего current | PASS | SHA без истории отвергается; перед переносом обязательны история/evidence и live content verification |
| 4 | Проверяемая история успехов | PASS | События с manifest, evidence, parent/hash; проверки существования commits и неизменяемого префикса |
| 5 | Первый deploy с пустой metadata | PASS | A / пусто; прежняя production-версия остаётся неизвестной |
| 6 | Повтор не создаёт ложный previous | PASS | A / пусто → A / пусто; B / A → B / A; сохраняется новый журнал verification |
| 7 | Только явная команда DEPLOY | PASS | Удалён обход проверок; все skills согласованы с AGENTS.md, включая загрузку rollback |
| 8 | Проверка PPNeueMontreal без изменения сайта | PASS | PPNeueMontreal указан только в CSS-комментарии; отсутствие этих файлов не является ошибкой активных ресурсов |
| 9 | Проверка содержимого | PASS | rsync -c, SHA-256 snapshot, remote и HTTP; изменение с прежними size/mtime обнаруживается |
| 10 | Совместимость rollback | PASS | Подтверждённый previous обязателен; успешный rollback меняет B / A на A / B |

## Выполненные локальные проверки

| Проверка | Результат | Детали |
| --- | --- | --- |
| git pull перед изменениями | PASS | При повторной проверке fast-forward до 29cac2c; получены существующие изменения HTML/иконок из origin/main |
| unittest discover | PASS | 29 тестов, 16.907 s, OK |
| Первый deploy, повтор и две версии | PASS | Проверены чистые переходы и запись/повторное чтение временных metadata |
| Rollback к подтверждённому target | PASS | B / A → A / B; без previous операция отвергается |
| Неполная/ошибочная verification | PASS | Ошибка upload/HTTP, отсутствующие hashes/statuses/журнал не создают успешного события |
| SHA без evidence / повреждение истории | PASS | Ошибка валидации, без fallback на произвольный Git commit |
| Изменённая metadata / lock / прерванная запись | PASS | Перезапись блокируется; неполные зеркала обнаруживаются; upload не повторяется |
| Snapshot и content checks | PASS | Symlinks отвергаются; content tampering с теми же size/mtime обнаруживается |
| Локальный rsync checksum dry-run | PASS | Реальный rsync -rvzcn на двух временных каталогах обнаружил различие; target не изменён |
| production.py inspect реального проекта | PASS | current=null, previous=null; реальные SHA-файлы остались по 0 байт |
| production.py check HEAD: ресурсы сайта | PASS | HEAD 29cac2cf451e1136fb6da36ac5d091f8efd595d9; missing_references=[]; exit code 0 |
| git diff --check | PASS | Ошибок whitespace нет |
| Изменения содержимого сайта/metadata | PASS | git diff по index.html/style.css/cases/js/assets/.deploy пуст |

Команды:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 python3 scripts/production.py inspect
PYTHONDONTWRITEBYTECODE=1 python3 scripts/production.py check HEAD
git diff --check
```

## Оставшиеся риски и решения

1. Файлы PPNeueMontreal отсутствуют, но все три примера @font-face находятся внутри
   CSS-комментария. Браузер не запрашивает их; блокировки deploy по этой причине нет.
   Активный стек и подключения Google Fonts сохранены. Доступность внешних шрифтов
   не проверялась этой локальной проверкой.
2. Текущий production commit по-прежнему неизвестен. Первый успешный deploy создаст
   только current; previous появится после успешной публикации другой версии.
3. Hash chain не заменяет подпись сервера: достоверность зависит от фактических
   журналов verification, проверки live content и сохранённой Git history.
4. Три metadata-файла не образуют одну filesystem-транзакцию. Частичный сбой
   обнаруживается; восстановление зеркал требует проверки и отдельного разрешения.
5. rsync не обеспечивает атомарную смену всей версии сайта. При ошибке возможна
   частичная загрузка; правила требуют остановки и не записывают ложный успех.
6. Процесс должен выполняться эксклюзивно. Lock защищает запись metadata в одной
   рабочей копии; независимые машины и ручные изменения сервера требуют координации.
7. Динамические ссылки JS, внешние ресурсы и серверные файлы за пределами allowlist
   не покрываются автоматической проверкой ссылок. Их проверка остаётся явным
   preflight шагом. Новые production paths требуют пересмотра allowlist.
8. Удалённые в новой версии файлы остаются на сервере без отдельного разрешения
   удаления. При влиянии на поведение deploy/rollback должен остановиться.
9. Удалённые upload/HTTP проверки в этом запуске не выполнялись по ограничению
   «только локально». Полная проверка нового процесса на production не заявляется.

Общий результат локальных изменений и тестов: **PASS**.
Ресурсный preflight текущего HEAD: **PASS**. Полный production preflight и готовность
к реальной загрузке в этом локальном запуске не проверялись.

Project commit, push, реальный deploy/rollback не выполнялись. Git commits в тестах
создавались только в изолированных временных repos и удалены вместе с ними.
Работа остановлена для проверки пользователем.


## Исправление ложного FAIL проверки CSS-ссылок

Повторная проверка: 2026-10-08.

Причина: missing_references искал url() в исходном CSS, включая комментарии.
Закомментированные примеры @font-face PPNeueMontreal ошибочно считались активными
ресурсами. Первоначальный FAIL и вывод о блокировке deploy были неверны.

Теперь CSS-комментарии удаляются из анализируемого текста перед поиском ссылок.
Строковые значения сохраняются, включая буквальные comment delimiters внутри URL.
Активные url() и @font-face продолжают проверяться; сайт не редактировался.

| Регрессионный сценарий | Результат |
| --- | --- |
| URL только внутри комментария | PASS — отсутствующий пример игнорируется |
| Отсутствующий URL в активном @font-face | PASS — корректно обнаружен FAIL ресурса |
| Существующий URL в активном @font-face | PASS — missing_references пуст |
| Комментарии и активные ссылки вместе | PASS — обнаружен только реально отсутствующий активный ресурс |

Весь набор: **29/29 PASS**. Команда `python3 scripts/production.py check HEAD`:
**PASS**, exit code 0, missing_references=[].
Проверенный SHA: `29cac2cf451e1136fb6da36ac5d091f8efd595d9`.

В этом исправлении изменены только scripts/production.py, tests/test_production.py
и этот отчёт. Обязательный git pull получил ранее опубликованные изменения
HTML/иконок из origin/main; это отдельное обновление существующей истории.
После pull локальный diff сайта и production metadata пуст.
Deploy, rollback, commit и push в основном репозитории не выполнялись.
