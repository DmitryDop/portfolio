#!/usr/bin/env python3
# Выгрузка кадров кейса 06 «Отпуска» из Figma MCP (download_assets, scale 2).
# Узлы — рамки кадров внутри белых карточек .media-card; выгружаются ровно по
# рамке, поэтому кроп не нужен (как в кейсах 04 и 05).
#
# Запуск:  python3 tmp/export_case06.py [имя-файла ...]
import json, os, re, subprocess, sys

sys.path.insert(0, "/Users/dmitry/portfolio/tmp")
from figma_mcp import call

FILE = "TYNqJkD1n3JizBkifaOE8t"
OUT = "/Users/dmitry/portfolio/assets/img/case-06"

NODES = [
    ("section-02", "911:5611", "624x403"),    # 01 Контекст — график отпусков
    ("section-03", "927:6878", "624x403"),    # 02 Планирование — календарь + модалка
    ("section-04", "927:6978", "624x355.33"), # 03 Пересечения
    ("section-05", "928:6985", "624x296.60"), # 04 Сценарии руководителя
    ("section-06", "941:11209", "624x403.51"),# 05 Статусы и связь с 1С
    ("section-07", "941:11212", "624x468"),   # 06 Мобильная версия
    ("section-08", "939:9305", "375x212"),    # Результат/итог — заглушка Empty
]


def export(node, path, rid):
    st, out = call("tools/call", {"name": "download_assets", "arguments": {
        "fileKey": FILE, "nodeId": node, "defaultFormat": "png", "defaultScale": 2}}, rid=rid)
    frames = re.findall(r"^data: (.*)$", out, re.M)
    if not frames:
        return "нет SSE-кадров: " + out[:300]
    payload = json.loads(frames[-1])
    if "error" in payload:
        return "ошибка MCP: " + json.dumps(payload["error"], ensure_ascii=False)[:300]
    content = payload["result"]["content"]
    text = next((c["text"] for c in content if c.get("type") == "text"), None)
    if text is None:
        return "нет текстового блока: " + json.dumps(content)[:300]
    data = json.loads(text)
    url = (data.get("export") or {}).get("url")
    if not url:
        return "нет export.url, ключи: " + ", ".join(sorted(data.keys()))
    r = subprocess.run(["curl", "-sS", "--max-time", "120", "-o", path,
                        "-w", "%{http_code}", url], capture_output=True, text=True)
    return r.stdout.strip() + " " + r.stderr.strip()


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    only = sys.argv[1:]
    rid = 10
    for name, node, expect in NODES:
        if only and name not in only:
            continue
        path = os.path.join(OUT, name + ".png")
        res = export(node, path, rid)
        rid += 1
        size = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", path],
                              capture_output=True, text=True).stdout
        w = re.search(r"pixelWidth: (\d+)", size)
        h = re.search(r"pixelHeight: (\d+)", size)
        got = f"{w.group(1)}x{h.group(1)}" if w and h else "?"
        print(f"{name:11} {node:9} ожидалось {expect:10} пришло {got:10} HTTP {res}")
