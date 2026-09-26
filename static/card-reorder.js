/* Move the cards on a page into whatever order you work in.
 *
 * Mark an area with data-reorder="<storage key>" and each column in it with
 * data-reorder-col="<name>" (the area itself can be the only column). Every
 * direct child with data-card-key is a card. Cards are dragged by their
 * title -- or by an existing .card-drag-handle -- so a drag never fights with
 * a link or a button inside the card, and can move between columns.
 *
 * The order is remembered per browser, not per record: it is how one person
 * likes to see their own screen, not business data anybody else reads. A
 * card the saved order has never heard of stays where the page put it, and a
 * saved key that no longer exists is ignored.
 *
 * Keyboard: focus a card's title, then the arrow keys move it up and down,
 * or left and right between columns.
 *
 * Phones and tablets cannot drag this way, so each card also gets a ▲ ▼
 * pair, shown only on touch screens (see .card-move in akye.css). The
 * columns stack into one list there, so moving up from the top of one
 * column lands at the bottom of the column above it, and every position on
 * the page is reachable.
 */
(function () {
  'use strict';

  function columnsOf(board) {
    if (board.hasAttribute('data-reorder-col')) return [board];
    return Array.prototype.slice.call(board.querySelectorAll('[data-reorder-col]'));
  }

  function cardsOf(col) {
    return Array.prototype.slice.call(col.children).filter(function (el) {
      return el.hasAttribute('data-card-key');
    });
  }

  function restore(board, key, cols) {
    var saved;
    try { saved = JSON.parse(localStorage.getItem(key) || 'null'); } catch (e) { return; }
    if (!saved) return;
    // An earlier version saved one plain list for a single column.
    if (Array.isArray(saved)) {
      var only = {};
      only[cols[0].getAttribute('data-reorder-col')] = saved;
      saved = only;
    }
    cols.forEach(function (col) {
      var keys = saved[col.getAttribute('data-reorder-col')];
      if (!Array.isArray(keys)) return;
      keys.forEach(function (k) {
        var card = board.querySelector('[data-card-key="' + String(k).replace(/"/g, '') + '"]');
        if (card) col.appendChild(card);
      });
    });
  }

  function save(key, cols) {
    var out = {};
    cols.forEach(function (col) {
      out[col.getAttribute('data-reorder-col')] = cardsOf(col).map(function (c) {
        return c.getAttribute('data-card-key');
      });
    });
    try { localStorage.setItem(key, JSON.stringify(out)); } catch (e) { /* private mode: the move still happened */ }
  }

  function handleFor(card) {
    var handle = card.querySelector(':scope > .card-drag-handle');
    if (handle) return handle;
    handle = card.querySelector(':scope > h2, :scope > h3');
    if (handle) {
      handle.classList.add('card-drag-title');
      var grip = document.createElement('span');
      grip.className = 'card-grip';
      grip.setAttribute('aria-hidden', 'true');
      grip.textContent = '⠿';
      handle.insertBefore(grip, handle.firstChild);
      return handle;
    }
    handle = document.createElement('span');
    handle.className = 'card-drag-handle';
    handle.textContent = '⠿';
    card.insertBefore(handle, card.firstChild);
    return handle;
  }

  function init(board) {
    var key = board.getAttribute('data-reorder');
    var cols = columnsOf(board);
    if (!key || !cols.length) return;
    restore(board, key, cols);

    // One step up (-1) or down (+1) in the page as it reads top to bottom:
    // past the end of a column, into the next one.
    function step(card, dir) {
      var col = card.parentElement;
      var sib = dir < 0 ? card.previousElementSibling : card.nextElementSibling;
      while (sib && !sib.hasAttribute('data-card-key')) {
        sib = dir < 0 ? sib.previousElementSibling : sib.nextElementSibling;
      }
      if (sib) {
        col.insertBefore(card, dir < 0 ? sib : sib.nextSibling);
        return true;
      }
      var next = cols[cols.indexOf(col) + dir];
      if (!next) return false;
      if (dir < 0) next.appendChild(card); else next.insertBefore(card, next.firstChild);
      return true;
    }

    function allCards() {
      return cols.reduce(function (acc, col) { return acc.concat(cardsOf(col)); }, []);
    }

    function refreshButtons() {
      var all = allCards();
      all.forEach(function (card, i) {
        var up = card.querySelector(':scope > .card-move > [data-dir="-1"]');
        var down = card.querySelector(':scope > .card-move > [data-dir="1"]');
        if (up) up.disabled = i === 0;
        if (down) down.disabled = i === all.length - 1;
      });
    }

    function addButtons(card) {
      var title = card.querySelector(':scope > h2, :scope > h3');
      var name = title ? title.textContent.replace('⠿', '').trim().replace(/\s+/g, ' ').slice(0, 40)
                       : 'this box';
      var row = document.createElement('div');
      row.className = 'card-move';
      [[-1, '▲', 'up'], [1, '▼', 'down']].forEach(function (b) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'card-move-btn';
        btn.setAttribute('data-dir', String(b[0]));
        btn.setAttribute('aria-label', 'Move "' + name + '" ' + b[2]);
        btn.textContent = b[1];
        btn.addEventListener('click', function () {
          if (!step(card, b[0])) return;
          save(key, cols);
          refreshButtons();
          btn.focus();
          card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        });
        row.appendChild(btn);
      });
      card.insertBefore(row, card.firstChild);
    }

    var dragging = null;
    function clearMarks() {
      board.querySelectorAll('.drag-over, .drag-over-col').forEach(function (el) {
        el.classList.remove('drag-over', 'drag-over-col');
      });
    }

    cols.forEach(function (col) {
      cardsOf(col).forEach(function (card) {
        var handle = handleFor(card);
        addButtons(card);
        handle.setAttribute('draggable', 'true');
        handle.setAttribute('tabindex', '0');
        handle.setAttribute('title', 'Drag to move this box — or focus it and use the arrow keys');

        handle.addEventListener('dragstart', function (e) {
          dragging = card;
          card.classList.add('dragging');
          e.dataTransfer.effectAllowed = 'move';
          // Firefox fires no further drag events without some data set.
          e.dataTransfer.setData('text/plain', card.getAttribute('data-card-key'));
        });
        handle.addEventListener('dragend', function () {
          card.classList.remove('dragging');
          clearMarks();
          dragging = null;
          save(key, cols);
          refreshButtons();
        });

        handle.addEventListener('keydown', function (e) {
          var colIndex = cols.indexOf(card.parentElement);
          var moved = false;
          if (e.key === 'ArrowUp') {
            moved = step(card, -1);
          } else if (e.key === 'ArrowDown') {
            moved = step(card, 1);
          } else if (e.key === 'ArrowLeft' && colIndex > 0) {
            cols[colIndex - 1].appendChild(card);
            moved = true;
          } else if (e.key === 'ArrowRight' && colIndex > -1 && colIndex < cols.length - 1) {
            cols[colIndex + 1].appendChild(card);
            moved = true;
          }
          if (moved) {
            e.preventDefault();
            handle.focus();
            save(key, cols);
            refreshButtons();
          }
        });

        card.addEventListener('dragover', function (e) {
          if (!dragging || dragging === card) return;
          e.preventDefault();
          e.stopPropagation();
          clearMarks();
          card.classList.add('drag-over');
        });
        card.addEventListener('drop', function (e) {
          if (!dragging || dragging === card) return;
          e.preventDefault();
          e.stopPropagation();
          // Dropped on the top half means "before this card", not after.
          var box = card.getBoundingClientRect();
          var before = (e.clientY - box.top) < box.height / 2;
          card.parentElement.insertBefore(dragging, before ? card : card.nextSibling);
          clearMarks();
        });
      });

      // The column itself: an empty one, or the space below its last card.
      col.addEventListener('dragover', function (e) {
        if (!dragging) return;
        e.preventDefault();
        if (!e.target.closest('[data-card-key]')) {
          clearMarks();
          col.classList.add('drag-over-col');
        }
      });
      col.addEventListener('drop', function (e) {
        if (!dragging || e.target.closest('[data-card-key]')) return;
        e.preventDefault();
        col.appendChild(dragging);
        clearMarks();
      });
    });
    refreshButtons();
  }

  function start() {
    document.querySelectorAll('[data-reorder]').forEach(init);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
