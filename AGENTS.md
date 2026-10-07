
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
- Перед загрузкой зафиксировать полный SHA и создать отдельный snapshot из Git blobs этого commit.
- Рабочую директорию не использовать как источник rsync. Dry-run выполнять с checksum (`-c`).
- Команда `DEPLOY` разрешает только показанный план с конкретным SHA и manifest; обхода проверок нет.
- Реальный rollback также является загрузкой и требует `DEPLOY` для конкретного rollback-плана.
- SHA в metadata сам по себе не подтверждает успешный deploy: обязательны история событий и SHA-256 verification.
- Общая схема metadata, первого deploy и rollback описана в `docs/production-protocol.md`.
- Не менять шрифты и ссылки сайта без согласования. Отсутствующие ресурсы блокируют deploy.
- Commit и push production metadata не выполнять автоматически; требуется отдельное разрешение.
