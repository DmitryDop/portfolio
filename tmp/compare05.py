#!/usr/bin/env python3
# Сравнение макета кейса 05 с вёрсткой: два пробника для голового Chrome.
#   tmp/case05-compare.html — обе страницы целиком, один масштаб, по колонкам;
#   tmp/case05-zoom.html    — четыре спорных места (01, 02, 06, 07) в увеличении.
# Кадры берутся из tmp/case05-figma-frame.png (экспорт фрейма 785:4922, 1319×4096)
# и tmp/case05-render.png (скриншот страницы, 1440×4475).
#
# Запуск: python3 tmp/compare05.py && Chrome --headless=new --screenshot=…
import io

FRAME_W, FRAME_H = 1440, 4475          # координаты в пикселях макета
FIGMA = ("case05-figma-frame.png", 1319, 4096)
RENDER = ("case05-render.png", 1440, 4475)

HEAD = u"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>%(title)s</title>
<style>
  html, body { margin: 0; background: #556; font: 12px/1.4 -apple-system, Arial, sans-serif; color: #fff; }
  .wrap { padding: 12px; }
  h1 { font-size: 14px; margin: 0 0 10px; font-weight: 600; }
  .cols { display: flex; gap: 16px; align-items: flex-start; }
  .col h2 { font-size: 12px; margin: 0 0 6px; font-weight: 600; color: #ffd; }
  canvas { display: block; background: #fff; }
  .panel { margin: 0 0 18px; }
  .panel h2 { font-size: 12px; margin: 0 0 6px; font-weight: 600; color: #ffd; }
  .panel .sub { font-size: 11px; color: #ccd; margin: 0 0 4px; }
</style></head><body><div class="wrap"><h1>%(title)s</h1>
"""

TAIL = u"""</div>
<script>
var FIG = %(fig)s, REN = %(ren)s, FW = %(fw)d, FH = %(fh)d;
function load(src){return new Promise(function(r){var i=new Image();i.onload=function(){r(i);};i.src=src;});}
function draw(img, meta, canvas, box, scale){
  // box — прямоугольник в координатах макета (x, y, w, h)
  var kx = meta[1] / FW, ky = meta[2] / FH;
  var c = canvas, x = c.getContext('2d');
  c.width = Math.round(box[2] * scale); c.height = Math.round(box[3] * scale);
  x.imageSmoothingQuality = 'high';
  x.drawImage(img, box[0] * kx, box[1] * ky, box[2] * kx, box[3] * ky,
              0, 0, c.width, c.height);
}
function pair(fig, ren, host, box, scale, tag){
  var p = document.createElement('div'); p.className = 'panel';
  var h = document.createElement('h2'); h.textContent = tag; p.appendChild(h);
  [['макет', fig, FIG], ['вёрстка', ren, REN]].forEach(function (t, i) {
    var s = document.createElement('p'); s.className = 'sub';
    s.textContent = t[0] + ' — x ' + box[0] + '…' + (box[0] + box[2]) +
                    ', y ' + box[1] + '…' + (box[1] + box[3]) + ' при 1440 (×' + scale + ')';
    var c = document.createElement('canvas'); p.appendChild(s); p.appendChild(c);
    draw(t[1], t[2], c, box, scale);
  });
  host.appendChild(p);
}
Promise.all([load(FIG[0]), load(REN[0])]).then(function (im) {
  var fig = im[0], ren = im[1];
  %(body)s
});
</script></body></html>
"""

COMPARE_BODY = u"""var host = document.createElement('div');
  host.className = 'cols';
  document.querySelector('.wrap').appendChild(host);
  [['макет', fig, FIG], ['вёрстка', ren, REN]].forEach(function (t) {
    var col = document.createElement('div'); col.className = 'col';
    var h = document.createElement('h2'); h.textContent = t[0];
    var c = document.createElement('canvas');
    col.appendChild(h); col.appendChild(c); host.appendChild(col);
    draw(t[1], t[2], c, [0, 0, FW, FH], 0.45);
  });"""

ZOOM_BODY = u"""var host = document.querySelector('.wrap');
  pair(fig, ren, host, [690, 690, 710, 380], 1.15, '01 — подпись «Интерфейс до редизайна» поверх кадра');
  pair(fig, ren, host, [100, 1360, 420, 360], 1.5,  '02 — абзац и «Ссылка на презентацию»');
  pair(fig, ren, host, [100, 3440, 460, 260], 1.5,  '06 — первая строка абзаца (единый узел в макете)');
  pair(fig, ren, host, [100, 3860, 1300, 260], 0.95, '07 — секция без номера и заглушка пустого состояния');"""

# По одному месту на файл — так увеличенные кадры попадают в окно голового
# Chrome целиком, без обрезки снизу
ZOOM_ONE = u"""pair(fig, ren, document.querySelector('.wrap'),
    %(box)s, %(scale)s, '%(tag)s');"""


PANELS = [
    ("01", [690, 690, 710, 380], 1.15, "01 — подпись «Интерфейс до редизайна» поверх кадра"),
    ("02", [100, 1360, 420, 360], 1.5, "02 — абзац и «Ссылка на презентацию»"),
    ("06", [100, 3440, 460, 260], 1.5, "06 — первая строка абзаца (единый узел в макете)"),
    ("07", [100, 3860, 1300, 260], 0.95, "07 — секция без номера и заглушка пустого состояния"),
]


def main():
    jobs = [
        ("tmp/case05-compare.html", "Кейс 05: макет и вёрстка целиком (масштаб 0.45)", COMPARE_BODY),
        ("tmp/case05-zoom.html", "Кейс 05: четыре спорных места (увеличение)", ZOOM_BODY),
    ]
    for num, box, scale, tag in PANELS:
        jobs.append((
            "tmp/case05-zoom-%s.html" % num,
            "Кейс 05: %s" % tag,
            ZOOM_ONE % {"box": "[%d, %d, %d, %d]" % tuple(box), "scale": scale, "tag": tag},
        ))
    for path, title, body in jobs:
        html = (HEAD % {"title": title}) + TAIL % {
            "fig": '["%s", %d, %d]' % FIGMA,
            "ren": '["%s", %d, %d]' % RENDER,
            "fw": FRAME_W, "fh": FRAME_H, "body": body,
        }
        with io.open("/Users/dmitry/portfolio/" + path, "w", encoding="utf-8") as f:
            f.write(html)
        print("собрано:", path)


if __name__ == "__main__":
    main()
