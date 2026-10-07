
# Portfolio project rules

## Git
- Перед началом работы выполняй `git pull`.
- После завершения изменений проверяй `git diff`.
- Коммит и push разрешены после успешной проверки изменений.

## Production
- Production: https://dopler.lineband.ru
- Никогда не выполняй deploy автоматически после commit или push.
- Deploy разрешён только после явной команды пользователя: `DEPLOY`.
- Перед deploy проверить рабочую директорию, текущий commit и целевые файлы.
- После deploy проверить production.
- Хранить текущую и предыдущую production-версию для rollback.
