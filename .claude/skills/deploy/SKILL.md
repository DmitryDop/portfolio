---
name: deploy
description: Проверяемый deploy portfolio из зафиксированного Git commit.
---

# Deploy

Единый источник инструкций — `.agents/skills/deploy/SKILL.md`.
Обязательно прочитай его, `AGENTS.md` и `docs/production-protocol.md` и следуй им.
Реальный deploy разрешён только после отдельной команды `DEPLOY` для показанного
плана. Обхода проверок нет. Snapshot из commit, SHA-256 verification и история
успешных операций обязательны. Размер и mtime не подтверждают содержимое.
