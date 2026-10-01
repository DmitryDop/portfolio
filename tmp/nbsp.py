#!/usr/bin/env python3
# Расставляет неразрывные пробелы после коротких предлогов и союзов —
# правило типографики из CLAUDE.md проекта. Трогает только текстовые узлы:
# комментарии, теги и атрибуты остаются нетронутыми.
#
# Запуск:  python3 tmp/nbsp.py cases/reactor.html [--write]
import re
import sys

# Набор — по правилам проекта и по факту применения в кейсах 01—02
PREPS = ("и", "в", "на", "с", "у", "о", "а", "но", "к", "при")

NBSP = " "
TOKEN = re.compile(
    r"(?<![\w ])(" + "|".join(PREPS) + r")[ ](?![< ])",
    re.IGNORECASE,
)


def fix_text(text):
    return TOKEN.sub(lambda m: m.group(1) + NBSP, text)


def process(html):
    """Идём по документу, пропуская комментарии и теги."""
    out = []
    pos = 0
    for m in re.finditer(r"<!--.*?-->|<[^>]*>", html, re.S):
        out.append(fix_text(html[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(fix_text(html[pos:]))
    return "".join(out)


def main():
    path = sys.argv[1]
    write = "--write" in sys.argv
    src = open(path, encoding="utf-8").read()
    dst = process(src)

    before = src.count(NBSP)
    after = dst.count(NBSP)
    print(f"{path}: NBSP {before} -> {after} (+{after - before})")

    # Контроль: ни одного тега или атрибута не тронуто
    strip = lambda s: re.sub(r"\s+", " ", re.sub(r"[^\s]+", "X", s))
    if strip(src) != strip(dst):
        print("  !! структура документа изменилась — правка отменена")
        return 1

    if write:
        open(path, "w", encoding="utf-8").write(dst)
        print("  записано")
    else:
        print("  (пробный прогон, без --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
