/* ============================================================================
   Дмитрий Дружков — портфолио
   Интерактив без библиотек: шапка при скролле, бургер-меню, активный пункт
   навигации, табы портфолио, появление блоков. Все эффекты уважают
   prefers-reduced-motion.
   ========================================================================= */

(function () {
  'use strict';

  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------------------------- Шапка при скролле ------------------------- */

  var header = document.getElementById('header');
  var hero = document.querySelector('.hero');

  function updateHeader() {
    if (!header) return;
    // Фон появляется, когда строка показателей подходит к шапке: пока идёт
    // хиро, навигация белая и лежит прямо на фото — как в макете.
    var threshold = hero ? hero.offsetHeight - 96 : 80;
    header.classList.toggle('is-scrolled', window.scrollY > threshold);
  }

  /* ------------------------------ Бургер-меню ----------------------------- */

  var burger = document.getElementById('burger');
  var nav = document.getElementById('nav');

  // Порядок обхода внутри меню: ссылки панели → CTA → бургер (замыкается)
  function menuFocusables() {
    var items = Array.prototype.slice.call(nav.querySelectorAll('a[href], button'));
    if (burger) items.push(burger);
    return items;
  }

  function setMenu(open, returnFocus) {
    if (!burger || !nav) return;
    nav.classList.toggle('is-open', open);
    burger.setAttribute('aria-expanded', String(open));
    burger.setAttribute('aria-label', open ? 'Закрыть меню' : 'Открыть меню');
    document.body.style.overflow = open ? 'hidden' : '';

    // Фокус уходит в панель при открытии и возвращается на бургер при закрытии
    if (open) {
      var first = nav.querySelector('a[href]');
      if (first) first.focus();
    } else if (returnFocus) {
      burger.focus();
    }
  }

  function menuIsOpen() {
    return nav && nav.classList.contains('is-open');
  }

  if (burger && nav) {
    burger.addEventListener('click', function () {
      setMenu(!menuIsOpen(), true);
    });

    // Esc закрывает меню; Tab не выпускает фокус за пределы панели и бургера
    document.addEventListener('keydown', function (e) {
      if (!menuIsOpen()) return;

      if (e.key === 'Escape') {
        setMenu(false, true);
        return;
      }

      if (e.key !== 'Tab') return;

      var items = menuFocusables();
      if (items.length < 2) return;

      var i = items.indexOf(document.activeElement);
      var next = i === -1 ? 0 : i + (e.shiftKey ? -1 : 1);
      if (next < 0) next = items.length - 1;
      if (next >= items.length) next = 0;

      e.preventDefault();
      items[next].focus();
    });

    document.addEventListener('click', function (e) {
      if (!menuIsOpen()) return;
      if (nav.contains(e.target) || burger.contains(e.target)) return;
      setMenu(false, true);
    });

    // Переход по ссылке закрывает меню
    nav.addEventListener('click', function (e) {
      if (e.target.closest('a')) setMenu(false);
    });

    // Возврат к десктопной раскладке сбрасывает состояние
    window.matchMedia('(min-width: 901px)').addEventListener('change', function (e) {
      if (e.matches) setMenu(false);
    });
  }

  /* ----------------------- Активный пункт навигации ----------------------- */

  var navLinks = Array.prototype.slice.call(document.querySelectorAll('.nav__link'));
  var navTargets = navLinks
    .map(function (link) {
      var id = link.getAttribute('href');
      var el = id && id.charAt(0) === '#' ? document.querySelector(id) : null;
      return el ? { link: link, el: el } : null;
    })
    .filter(Boolean);

  function updateActiveLink() {
    if (!navTargets.length) return;
    // Линия активации ниже якорного отступа (scroll-margin-top: 96px), иначе
    // цель, к которой только что привёл клик, оказывается ниже линии и пункт
    // не подсвечивается
    var line = (header ? header.offsetHeight : 0) + 48;
    var current = null;

    // Дошли до низа: обычное правило оставляет подсвеченной середину страницы
    // (подвал не вытесняет её за линию), поэтому берём самую глубокую
    // начавшуюся цель — это подвал, помеченный как «Обо мне»
    var atBottom = window.innerHeight + window.scrollY >=
                   document.documentElement.scrollHeight - 4;

    if (atBottom) {
      navTargets.forEach(function (item) {
        var top = item.el.getBoundingClientRect().top;
        if (top < window.innerHeight &&
            (!current || top > current.el.getBoundingClientRect().top)) {
          current = item;
        }
      });
    } else {
      navTargets.forEach(function (item) {
        if (item.el.getBoundingClientRect().top - line <= 0) current = item;
      });
    }

    navTargets.forEach(function (item) {
      item.link.classList.toggle('is-active', item === current);
    });
  }

  /* --------------------------- Табы портфолио ----------------------------- */
  /* Три экрана одного блока: «Страна Девелопмент» (сетка проектов),
     «Banki.ru» (ссылка на портфолио-прототип) и «Разное» (одна карточка
     «Палка-выручалка»). Разметка — по паттерну ARIA tabs: выбранный таб
     держит tabindex 0, остальные -1, стрелки/Home/End переключают с
     автоактивацией (панели дешёвые — отдельное подтверждение Enter'ом
     не нужно). */

  var tablist = document.getElementById('portfolio-tabs');

  if (tablist) {
    var tabs = Array.prototype.slice.call(tablist.querySelectorAll('[role="tab"]'));

    function selectTab(tab, moveFocus) {
      tabs.forEach(function (item) {
        var isOn = item === tab;
        item.setAttribute('aria-selected', String(isOn));
        item.tabIndex = isOn ? 0 : -1;

        // Панель показывается/прячется атрибутом hidden — правило [hidden]
        // в style.css перебивает display у .panel и его содержимого
        var panel = document.getElementById(item.getAttribute('aria-controls'));
        if (panel) panel.hidden = !isOn;
      });

      if (moveFocus) tab.focus();
    }

    tabs.forEach(function (tab, i) {
      tab.addEventListener('click', function () {
        selectTab(tab);
      });

      tab.addEventListener('keydown', function (e) {
        var last = tabs.length - 1;
        var next = null;

        if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = tabs[i === last ? 0 : i + 1];
        else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = tabs[i === 0 ? last : i - 1];
        else if (e.key === 'Home') next = tabs[0];
        else if (e.key === 'End') next = tabs[last];

        if (!next) return;
        e.preventDefault();
        selectTab(next, true);
      });
    });
  }

  /* ------------------------- Появление блоков ----------------------------- */

  var revealItems = document.querySelectorAll('.reveal');

  if (reduceMotion || !('IntersectionObserver' in window)) {
    Array.prototype.forEach.call(revealItems, function (el) {
      el.classList.add('is-visible');
    });
  } else {
    var revealObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-visible');
        revealObserver.unobserve(entry.target);
      });
    }, { rootMargin: '0px 0px -10% 0px', threshold: 0.08 });

    Array.prototype.forEach.call(revealItems, function (el) {
      revealObserver.observe(el);
    });
  }

  /* ------------------------------ Скролл-хендлер -------------------------- */

  var ticking = false;

  function onScroll() {
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(function () {
      updateHeader();
      updateActiveLink();
      ticking = false;
    });
  }

  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll);

  updateHeader();
  updateActiveLink();
})();
