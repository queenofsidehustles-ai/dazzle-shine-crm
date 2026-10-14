/* What a feature is for, where somebody is about to click it (help_tips.py).
 *
 * Two kinds, because they are read differently:
 *
 *  - Menu tips. Hovering (or tabbing to) a sidebar item or section tab shows
 *    one line on what it is for. Text only, read in passing, and never on a
 *    touch screen -- there a tap opens the page, which has its own ⓘ.
 *
 *  - The ⓘ button ({{ tip('key') }}, and beside each page's title). Tap,
 *    click or Enter opens it; it can hold links (a setup video, Ask Nana).
 *    With a mouse it also opens on hover, and a click pins it open.
 *
 * Esc closes either; so does clicking anywhere else.
 */
(function () {
  var canHover = window.matchMedia && window.matchMedia('(hover: hover) and (pointer: fine)').matches;
  // The visible width, not innerWidth: on a phone innerWidth can be the
  // zoomed-out layout width, and a tip kept inside that is off the screen.
  function vw() { return document.documentElement.clientWidth || window.innerWidth; }
  function vh() { return document.documentElement.clientHeight || window.innerHeight; }

  // ── Menu tips ────────────────────────────────────────────────────────
  var data = {};
  try { data = JSON.parse((document.getElementById('menuTips') || {}).textContent || '{}'); } catch (e) { data = {}; }
  var box = document.getElementById('menuTip');
  var timer = null, current = null, hiddenAt = 0;

  function place(el) {
    var r = el.getBoundingClientRect();
    var inSidebar = !!el.closest('.sidebar');
    box.style.left = '0px'; box.style.top = '0px';
    box.hidden = false;
    var w = box.offsetWidth, h = box.offsetHeight;
    var left = inSidebar ? r.right + 10 : r.left;
    var top = inSidebar ? r.top + (r.height - h) / 2 : r.bottom + 8;
    left = Math.max(8, Math.min(left, vw() - w - 8));
    top = Math.max(8, Math.min(top, vh() - h - 8));
    box.style.left = left + 'px'; box.style.top = top + 'px';
  }

  function showMenu(el) {
    var t = data[el.getAttribute('data-tip')];
    if (!t || !box) return;
    box.textContent = '';
    var b = document.createElement('strong'); b.textContent = t.title;
    box.appendChild(b);
    box.appendChild(document.createTextNode(' ' + t.text));
    if (t.locked) {
      var l = document.createElement('span'); l.className = 'menu-tip-lock';
      l.textContent = '🔒 ' + t.locked;
      box.appendChild(l);
    }
    place(el);
    el.setAttribute('aria-describedby', 'menuTip');
    current = el;
  }

  function hideMenu() {
    clearTimeout(timer);
    if (box) box.hidden = true;
    if (current) { current.removeAttribute('aria-describedby'); hiddenAt = Date.now(); }
    current = null;
  }

  document.querySelectorAll('[data-tip]').forEach(function (el) {
    if (canHover) {
      el.addEventListener('mouseenter', function () {
        clearTimeout(timer);
        // A moment's pause: a pointer passing over the menu on its way
        // somewhere else should not flash tips at people.
        // Moving from one item to the next, though, the next one shows at once.
        timer = setTimeout(function () { showMenu(el); },
                           (current || Date.now() - hiddenAt < 400) ? 0 : 450);
      });
      el.addEventListener('mouseleave', hideMenu);
    }
    el.addEventListener('focus', function () {
      if (el.matches(':focus-visible')) showMenu(el);
    });
    el.addEventListener('blur', hideMenu);
  });
  // The sidebar scrolls; a tip left behind would point at the wrong item.
  var side = document.getElementById('sidebar');
  if (side) side.addEventListener('scroll', hideMenu, { passive: true });

  // ── The ⓘ button ─────────────────────────────────────────────────────
  function popOf(btn) { return document.getElementById(btn.getAttribute('aria-controls')); }

  function openTip(btn, pinned) {
    closeAll(btn);
    var pop = popOf(btn);
    if (!pop) return;
    pop.hidden = false;
    btn.setAttribute('aria-expanded', 'true');
    if (pinned) btn.dataset.pinned = '1';
    // Kept on screen: on a phone the button can be near either edge. Lined
    // up with the button where it fits, slid left where it would not.
    var anchor = btn.parentElement.getBoundingClientRect();
    var w = pop.offsetWidth;
    var left = Math.max(8, Math.min(anchor.left - 8, vw() - w - 8));
    pop.style.right = 'auto';
    pop.style.left = (left - anchor.left) + 'px';
  }

  function closeTip(btn) {
    var pop = popOf(btn);
    if (pop) pop.hidden = true;
    btn.setAttribute('aria-expanded', 'false');
    delete btn.dataset.pinned;
  }

  function closeAll(except) {
    document.querySelectorAll('.tip-btn[aria-expanded="true"]').forEach(function (b) {
      if (b !== except) closeTip(b);
    });
  }

  document.querySelectorAll('.tip').forEach(function (wrap) {
    var btn = wrap.querySelector('.tip-btn');
    if (!btn) return;
    var hoverTimer = null;
    btn.addEventListener('click', function (e) {
      e.preventDefault(); e.stopPropagation();
      if (btn.getAttribute('aria-expanded') === 'true' && btn.dataset.pinned) closeTip(btn);
      else openTip(btn, true);
    });
    if (canHover) {
      wrap.addEventListener('mouseenter', function () {
        clearTimeout(hoverTimer);
        hoverTimer = setTimeout(function () {
          if (btn.getAttribute('aria-expanded') !== 'true') openTip(btn, false);
        }, 250);
      });
      wrap.addEventListener('mouseleave', function () {
        clearTimeout(hoverTimer);
        if (!btn.dataset.pinned) closeTip(btn);
      });
    }
  });

  document.addEventListener('click', function (e) {
    if (!e.target.closest('.tip')) closeAll(null);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    hideMenu();
    var open = document.querySelector('.tip-btn[aria-expanded="true"]');
    if (open) { closeTip(open); open.focus(); }
  });
})();
