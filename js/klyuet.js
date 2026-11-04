/* Просмотр оригинала сертификата; без JS ссылка открывает исходный PNG. */
(function () {
  'use strict';
  var link = document.querySelector('[data-certificate]');
  var viewer = document.querySelector('[data-certificate-viewer]');
  if (!link || !viewer || typeof viewer.showModal !== 'function') return;
  var close = viewer.querySelector('button');
  var scroll = viewer.querySelector('.certificate-viewer__scroll');
  var image = viewer.querySelector('img');

  link.addEventListener('click', function (event) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    viewer.showModal();
  });
  close.addEventListener('click', function () { viewer.close(); });
  viewer.addEventListener('click', function (event) {
    if (event.target === viewer || event.target === scroll) viewer.close();
  });
  image.addEventListener('click', function () {
    scroll.classList.toggle('is-zoomed');
    scroll.scrollTop = 0;
    scroll.scrollLeft = 0;
  });
  viewer.addEventListener('close', function () {
    scroll.classList.remove('is-zoomed');
    link.focus({ preventScroll: true });
  });
})();
