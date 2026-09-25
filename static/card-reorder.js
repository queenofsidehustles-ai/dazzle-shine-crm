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

    var dragging = null;
    function clearMarks() {
      board.querySelectorAll('.drag-over, .drag-over-col').forEach(function (el) {
        el.classList.remove('drag-over', 'drag-over-col');
      });
    }

    cols.forEach(function (col) {
      cardsOf(col).forEach(function (card) {
        var handle = handleFor(card);
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
        });

        handle.addEventListener('keydown', function (e) {
          var colIndex = cols.indexOf(card.parentElement);
          var moved = false;
          if (e.key === 'ArrowUp' && card.previousElementSibling) {
            card.parentElement.insertBefore(card, card.previousElementSibling);
            moved = true;
          } else if (e.key === 'ArrowDown' && card.nextElementSibling) {
            card.parentElement.insertBefore(card.nextElementSibling, card);
            moved = true;
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
