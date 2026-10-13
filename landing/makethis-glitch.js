/**
 * MakeThis Glitch Wordmark (makethis.si)
 * On page load, hover, focus, tap, or scroll into view, the wordmark shakes
 * and tears into horizontal slices with chromatic aberration layers in
 * MakeThis brand orange (#f5501a) and fintech blue (#1f4fd8).
 */
(function () {
  function mtGlitch(el) {
    if (!el || el.__glitch) return;
    el.__glitch = true;
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    var t = el.querySelector('.wm-t');
    var a = el.querySelector('.wm-a');
    var b = el.querySelector('.wm-b');
    if (!t || !a || !b) return;

    var timer = 0, until = 0;
    function slice() {
      var top = Math.random() * 80, h = 6 + Math.random() * 30;
      return 'inset(' + top.toFixed(1) + '% 0 ' + Math.max(0, 100 - top - h).toFixed(1) + '% 0)';
    }

    function frame() {
      var now = performance.now();
      if (now > until) {
        el.classList.remove('wm-on');
        t.style.transform = a.style.transform = b.style.transform = '';
        a.style.clipPath = b.style.clipPath = t.style.clipPath = '';
        timer = 0;
        return;
      }
      var k = (until - now) / 650;
      var dx = function (m) { return ((Math.random() - 0.5) * m * k).toFixed(1) + 'px'; };
      t.style.transform = 'translate(' + dx(3) + ',' + dx(1.5) + ')';
      t.style.clipPath = Math.random() < 0.35 ? slice() : '';
      a.style.clipPath = slice();
      b.style.clipPath = slice();
      a.style.transform = 'translate(' + dx(10) + ', 0)';
      b.style.transform = 'translate(' + dx(10) + ', 0)';
      timer = setTimeout(function () { requestAnimationFrame(frame); }, 45 + Math.random() * 35);
    }

    function play() {
      until = performance.now() + 650;
      el.classList.add('wm-on');
      if (!timer) frame();
    }

    el.addEventListener('pointerenter', play);
    el.addEventListener('focus', play);
    el.addEventListener('pointerdown', function (e) { if (e.pointerType !== 'mouse') play(); });

    var go = function () { setTimeout(play, 350); };
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(go);
    } else {
      go();
    }

    if ('IntersectionObserver' in window) {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            play();
            io.unobserve(el);
          }
        });
      }, { threshold: 0.1 });
      io.observe(el);
    }
  }

  function init() {
    document.querySelectorAll('.wm').forEach(function (w) { mtGlitch(w); });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
