# Локальные тесты production protocol

Запуск без production-доступа:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 python3 scripts/production.py baseline-plan HEAD
```

Все тестовые commits, history.json и SHA-зеркала создаются в disposable Git repos.
Основной репозиторий не коммитится; реальные metadata и сайт не меняются.
Нет SSH и запросов к production. Только отдельный интеграционный тест вызывает
rsync между временными локальными каталогами; HTTP-тела явно имитируются чтением
локальных файлов. Это не проверка реального сервера или исторического deploy.

Проверяются:

- baseline только при empty history/current/previous, pinned SHA и согласованный manifest;
- observation/upload evidence разделены; baseline не содержит выдуманный rsync exit code;
- подготовка плана и кандидата без записи; отказ без owner confirmation даже с env flags;
- повторная verification под lock; несовпадение SSH/HTTP hashes/statuses блокирует запись;
- изменение metadata после подготовки и во время повторной проверки блокирует запись;
- baseline A → deploy B → rollback A, содержимое, SHA, manifest и persisted history;
- обязательный live_current перед upload после baseline; повтор A не создаёт previous;
- отказ rollback после одного baseline; отказ второго baseline; защита цепочки;
- прежние deploy/rollback, interrupted writes, locks, CSS comment regression и snapshot checks.

Интеграционный тест проверяет внутренний storage primitive `_persist_history`
исключительно в disposable repo. Он не подменяет owner guard и не создаёт
фиктивного пользовательского подтверждения. Публичная adoption API остаётся
заблокированной: доверенный owner channel отсутствует. PASS локального storage
теста не означает, что реальная adoption разрешена или что подпись проверена.

Достоверность реальных observations, HTTP redirects/compression и защищённый
источник подтверждения требуют отдельного тестирования после подключения внешнего
доверенного компонента. Никаких production операций этот набор не выполняет.

## Результаты запуска 2026-10-08

| Проверка | Результат |
| --- | --- |
| Полный unittest discover | PASS — 47 тестов, 36.355 s, OK |
| Baseline A → deploy B → rollback A | PASS — A/пусто → B/A → A/B; manifest, bytes и persisted history |
| Исходные deploy/rollback и CSS-ссылки | PASS |
| Отказы при mismatch, изменении metadata и отсутствии owner confirmation | PASS |
| Повторная observation под lock; ошибка повторной verification | PASS — история не записывается |
| baseline-plan HEAD основного проекта | PASS — pinned 29cac2cf451e1136fb6da36ac5d091f8efd595d9, без SSH/HTTP и записи |
| inspect основного проекта | PASS — current=null, previous=null |
| git diff --check и diff сайта/metadata | PASS — whitespace errors нет; diff сайта/metadata пуст |

Bundled quick_validate skills не запустился: в системном Python отсутствует PyYAML.
Зависимости не устанавливались; YAML frontmatter проверен отдельно Ruby/Psych.
Фактическая adoption **НЕ ДОСТУПНА**: защищённый owner channel ещё не подключён.
Ни production verification, ни baseline adoption в этом запуске не выполнялись.
