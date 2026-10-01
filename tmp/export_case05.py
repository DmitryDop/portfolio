#!/usr/bin/env python3
# Выгрузка кадров кейса 05 «Наш Дом Pro» из Figma MCP (download_assets, scale 2).
# Узлы — рамки кадров внутри белых карточек .media-card; выгружаются ровно по
# рамке, поэтому кроп не нужен (как в кейсе 04).
#
# Запуск:  python3 tmp/export_case05.py [имя-файла ...]
import json, os, re, subprocess, sys

sys.path.insert(0, "/Users/dmitry/portfolio/tmp")
from figma_mcp import call

FILE = "TYNqJkD1n3JizBkifaOE8t"
OUT = "/Users/dmitry/portfolio/assets/img/case-05"

NODES = [
    ("section-01", "818:12451", "600x432"),
    ("section-02", "788:9147", "532x366"),
    ("section-03", "805:12440", "624x482"),
    ("section-04", "798:9582", "600x400"),
    ("section-05", "801:12398", "600x400"),
    ("section-06", "829:3753", "600x349"),   # кадр-композиция из компонентов, не одиночная картинка
    ("section-07", "801:12419", "375x212"),
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
        print(f"{name:11} {node:9} ожидалось {expect:8} пришло {got:8} HTTP {res}")
