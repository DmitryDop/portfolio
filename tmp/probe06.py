#!/usr/bin/env python3
# Пробник вёрстки кейса 06: копия страницы в tmp/ со скриптом замера.
# Печатает y/h/bottom/w по блокам, битые картинки, scrollWidth и docHeight.
#
# Запуск:  python3 tmp/probe06.py && "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
#            --headless=new --virtual-time-budget=6000 --window-size=1440,1000 --dump-dom \
#            file:///Users/dmitry/portfolio/tmp/case06-measure.html | sed -n '/MEASURE/,/<\/pre>/p'
import io, os, sys

ROOT = "/Users/dmitry/portfolio"
SRC = os.path.join(ROOT, "cases", "vacations.html")
DST = os.path.join(ROOT, "tmp", "case06-measure.html")

PROBE = """<style>
  /* В headless reveal-анимация может не доехать — блоки должны быть видны */
  .reveal { opacity: 1 !important; transform: none !important; }
</style>
<script>
window.addEventListener('load', function () {
  var out = [];
  function m(el, label) {
    if (!el) { out.push(label + ' MISSING'); return; }
    var r = el.getBoundingClientRect();
    out.push(label + ' y=' + Math.round(r.top + window.scrollY) +
             ' h=' + Math.round(r.height) +
             ' bottom=' + Math.round(r.bottom + window.scrollY) +
             ' w=' + Math.round(r.width));
  }
  m(document.querySelector('.header'), 'header');
  m(document.querySelector('.sub-header'), 'sub-header');
  m(document.querySelector('.case-hero'), 'hero');
  Array.prototype.forEach.call(document.querySelectorAll('.case-section'), function (el, i) {
    var n = (i + 1 < 10 ? '0' : '') + (i + 1);
    m(el, 'sec-' + n);
    m(el.querySelector('.case-media'), '    card');
    m(el.querySelector('.case-media__shot'), '    shot');
    m(el.querySelector('.case-section__text'), '    text');
  });
  m(document.querySelector('footer'), 'footer');
  out.push('scrollW=' + document.documentElement.scrollWidth +
           ' clientW=' + document.documentElement.clientWidth);
  out.push('docHeight=' + document.documentElement.scrollHeight);
  Array.prototype.forEach.call(document.images, function (im) {
    if (!im.naturalWidth) out.push('BROKEN ' + im.getAttribute('src'));
  });
  var pre = document.createElement('pre');
  pre.id = 'MEASURE';
  pre.textContent = 'MEASURE\\n' + out.join('\\n');
  document.body.appendChild(pre);
  /* ?down — прокрутить в самый низ: headless снимает вьюпорт, а не страницу,
     поэтому низ кейса иначе не увидеть */
  if (location.search.indexOf('down') >= 0) {
    window.scrollTo(0, document.documentElement.scrollHeight);
  }
});
</script>
"""


def main():
    with io.open(SRC, encoding="utf-8") as f:
        html = f.read()
    if "</body>" not in html:
        sys.exit("в исходнике нет </body>")
    html = html.replace("</body>", PROBE + "</body>", 1)
    with io.open(DST, "w", encoding="utf-8") as f:
        f.write(html)
    print("собрано:", DST)


if __name__ == "__main__":
    main()
