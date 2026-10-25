/* "Show me": walk an owner through a guide on the real screen (howto.py).
 *
 * Started by ?tour=<key> on any admin page -- the link Nana's Show me button
 * opens -- and carried from page to page in sessionStorage, so pressing the
 * highlighted New booking button lands on the new-booking form with the next
 * step already pointed at. The page stays fully usable: the dimming is a
 * shadow around a ring that ignores the mouse, never a sheet over the page.
 *
 * Everything is inserted as text, never as markup. Paths it navigates to come
 * from the guide and must be same-site.
 */
(function () {
  'use strict';
  var KEY = 'akye-tour';
  var params = new URLSearchParams(window.location.search);
  var state = null;
  try { state = JSON.parse(sessionStorage.getItem(KEY) || 'null'); } catch (e) { state = null; }
  if (params.get('tour')) {
    state = { key: params.get('tour'), step: 0 };
    params.delete('tour');
    var q = params.toString();
    try {
      window.history.replaceState(null, '', window.location.pathname + (q ? '?' + q : '') + window.location.hash);
    } catch (e) {}
  }
  if (!state || !/^[a-z0-9-]+$/.test(state.key || '')) return;

  function save() { try { sessionStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} }
  function stop() {
    try { sessionStorage.removeItem(KEY); } catch (e) {}
    [ring, bubble].forEach(function (n) { if (n && n.parentNode) n.parentNode.removeChild(n); });
    window.removeEventListener('resize', place);
    window.removeEventListener('scroll', place, true);
    document.removeEventListener('keydown', onKey);
  }
  function safePath(p) { return typeof p === 'string' && p.charAt(0) === '/' && p.charAt(1) !== '/' && p.charAt(1) !== '\\'; }
  function onPage(step) {
    try { return !step.page || new RegExp(step.page).test(window.location.pathname); } catch (e) { return false; }
  }

  var guide = null, ring = null, bubble = null, target = null;

  var css = document.createElement('style');
  css.textContent =
    '.tour-ring{position:fixed;z-index:2147483000;pointer-events:none;border-radius:10px;' +
    'box-shadow:0 0 0 4px #f0a44b,0 0 0 9999px rgba(22,33,58,.45);transition:all .2s ease}' +
    '.tour-bubble{position:fixed;z-index:2147483001;max-width:340px;width:calc(100vw - 32px);' +
    'background:#fff;color:#16213a;border-radius:14px;padding:14px 16px;font:15px/1.5 Inter,system-ui,sans-serif;' +
    'box-shadow:0 18px 40px rgba(22,33,58,.3)}' +
    '.tour-bubble .tour-n{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:#8a8fa3;margin-bottom:4px}' +
    '.tour-bubble .tour-t{font-weight:700;margin-bottom:6px}' +
    '.tour-bubble .tour-row{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}' +
    '.tour-bubble button,.tour-bubble a{font:inherit;font-size:14px;border-radius:999px;padding:7px 14px;cursor:pointer;' +
    'border:1px solid #d9dce5;background:#fff;color:#16213a;text-decoration:none}' +
    '.tour-bubble .tour-go{background:#f0a44b;border-color:#f0a44b;color:#1a1225;font-weight:700}' +
    '.tour-bubble .tour-x{margin-left:auto;border:0;color:#8a8fa3;padding:7px 4px}' +
    '@media (prefers-reduced-motion: reduce){.tour-ring{transition:none}}';
  document.head.appendChild(css);

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text) n.textContent = text;
    return n;
  }

  function place() {
    if (!bubble) return;
    var vw = window.innerWidth, vh = window.innerHeight;
    if (target && ring) {
      var r = target.getBoundingClientRect();
      ring.style.display = 'block';
      ring.style.left = (r.left - 6) + 'px';
      ring.style.top = (r.top - 6) + 'px';
      ring.style.width = (r.width + 12) + 'px';
      ring.style.height = (r.height + 12) + 'px';
      var bw = bubble.offsetWidth, bh = bubble.offsetHeight;
      var top = r.bottom + 14;
      if (top + bh > vh - 8) top = Math.max(8, r.top - bh - 14);
      var left = Math.min(Math.max(8, r.left), vw - bw - 8);
      bubble.style.left = left + 'px';
      bubble.style.top = top + 'px';
    } else {
      if (ring) ring.style.display = 'none';
      bubble.style.left = Math.max(8, (vw - bubble.offsetWidth) / 2) + 'px';
      bubble.style.top = Math.max(8, (vh - bubble.offsetHeight) / 3) + 'px';
    }
  }

  function onKey(e) { if (e.key === 'Escape') stop(); }

  function go(i) {
    state.step = i;
    save();
    show();
  }

  function show() {
    var steps = guide.steps || [];
    if (state.step >= steps.length) { stop(); return; }
    // Landed on a later step's page (the highlighted button navigated)?
    // Move forward to the first step that belongs here.
    if (!onPage(steps[state.step])) {
      for (var j = state.step + 1; j < steps.length; j++) {
        if (onPage(steps[j])) { state.step = j; save(); break; }
      }
    }
    var step = steps[state.step];
    var here = onPage(step);
    target = here && step.target ? document.querySelector('[data-tour="' + step.target.replace(/"/g, '') + '"]') : null;

    if (!ring) { ring = el('div', 'tour-ring'); document.body.appendChild(ring); }
    if (bubble) bubble.parentNode.removeChild(bubble);
    bubble = el('div', 'tour-bubble');
    bubble.setAttribute('role', 'dialog');
    bubble.setAttribute('aria-live', 'polite');
    bubble.appendChild(el('div', 'tour-n', 'Step ' + (state.step + 1) + ' of ' + steps.length + ' · ' + guide.title));
    bubble.appendChild(el('div', 'tour-t', step.say));
    var row = el('div', 'tour-row');

    if (!here) {
      bubble.appendChild(el('div', '', 'This step is on another page.'));
      if (safePath(step.start)) {
        var a = el('a', 'tour-go', 'Take me there →');
        a.href = step.start;
        row.appendChild(a);
      }
    } else {
      if (state.step > 0) {
        var back = el('button', '', '← Back');
        back.type = 'button';
        back.onclick = function () { go(state.step - 1); };
        row.appendChild(back);
      }
      var last = state.step === steps.length - 1;
      var next = el('button', 'tour-go', last ? 'Done' : 'Next →');
      next.type = 'button';
      next.onclick = function () {
        if (last) { stop(); return; }
        var nx = steps[state.step + 1];
        if (!onPage(nx) && safePath(nx.start) && !/\\d/.test(nx.page || '')) {
          state.step += 1; save();
          window.location.href = nx.start;
          return;
        }
        go(state.step + 1);
      };
      row.appendChild(next);
    }
    var x = el('button', 'tour-x', 'Exit');
    x.type = 'button';
    x.onclick = stop;
    row.appendChild(x);
    bubble.appendChild(row);
    document.body.appendChild(bubble);

    if (target) {
      // Doing the step moves the tour on, so the next page opens with the
      // next step pointed at. "Doing it" is pressing a button or link, or
      // submitting the form -- not clicking into a box or opening a dropdown
      // inside a highlighted card, which used to skip ahead before Send.
      var done = false;
      var advance = function () {
        if (done) return;
        done = true;
        state.step += 1; save();
        setTimeout(function () { if (document.body.contains(bubble)) show(); }, 250);
      };
      target.addEventListener('click', function (e) {
        var hit = e.target && e.target.closest ? e.target.closest('a, button, summary, [role="button"]') : null;
        if (!hit || !target.contains(hit)) return;
        // A submit button is counted when its form submits, below.
        if (hit.tagName === 'BUTTON' && (hit.type || 'submit') === 'submit' && hit.form) return;
        advance();
      });
      var form = target.tagName === 'FORM' ? target : target.querySelector('form');
      if (form) form.addEventListener('submit', advance);
      else if (target.form) target.form.addEventListener('submit', advance);
      try { target.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch (e) { target.scrollIntoView(); }
      setTimeout(place, 350);
    }
    place();
  }

  fetch('/help/tour/' + state.key + '.json', { headers: { 'Accept': 'application/json' } })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (g) {
      if (!g || !g.steps) { stop(); return; }
      guide = g;
      window.addEventListener('resize', place);
      window.addEventListener('scroll', place, true);
      document.addEventListener('keydown', onKey);
      show();
    })
    .catch(function () { stop(); });
})();
