/**
 * Faida Offline Engine v3
 * ─────────────────────────────────────────────────────────────────────────
 *  1. Register the Service Worker
 *  2. Detect online/offline → show/hide a non-blocking TOAST (auto-dismisses)
 *  3. Intercept form submits on key pages when offline
 *  4. Store pending ops in IndexedDB (faida_queue)
 *  5. Render pending ops immediately in the table so user sees what they saved
 *  6. Trigger sync on reconnect; update UI with results
 */

(function () {
  'use strict';

  // ── Constants ─────────────────────────────────────────────────────────────
  const DB_NAME    = 'faida_offline';
  const DB_VERSION = 1;
  const STORE_NAME = 'faida_queue';
  const ENDPOINTS  = {
    sale:           '/api/v1/sales',
    stock_purchase: '/api/v1/stock-purchases',
    cash_outflow:   '/api/v1/cash-outflows',
  };

  // ── State ─────────────────────────────────────────────────────────────────
  let db = null;

  // ── 1. Service Worker Registration ────────────────────────────────────────
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js', { scope: '/' })
        .then(function (reg) { console.log('[Faida] SW registered:', reg.scope); })
        .catch(function (err) { console.warn('[Faida] SW error:', err); });
    });
  }

  // ── 2. IndexedDB ──────────────────────────────────────────────────────────
  function initDB() {
    return new Promise(function (resolve, reject) {
      if (db) { resolve(db); return; }
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = function (e) {
        const d = e.target.result;
        if (!d.objectStoreNames.contains(STORE_NAME)) {
          const s = d.createObjectStore(STORE_NAME, { keyPath: 'id', autoIncrement: true });
          s.createIndex('status',   'status',   { unique: false });
          s.createIndex('local_id', 'local_id', { unique: true  });
        }
      };
      req.onsuccess = function (e) { db = e.target.result; resolve(db); };
      req.onerror   = function (e) { reject(e.target.error); };
    });
  }

  function queueOp(type, data) {
    return initDB().then(function (d) {
      return new Promise(function (resolve, reject) {
        const rec = {
          local_id:  data.local_id || generateUUID(),
          type,
          status:    'pending',
          data,
          queued_at: new Date().toISOString(),
        };
        const req = d.transaction(STORE_NAME, 'readwrite').objectStore(STORE_NAME).add(rec);
        req.onsuccess = function () { resolve(req.result); };
        req.onerror   = function (e) { reject(e.target.error); };
      });
    });
  }

  function getPendingOps() {
    return initDB().then(function (d) {
      return new Promise(function (resolve, reject) {
        const req = d.transaction(STORE_NAME, 'readonly')
                     .objectStore(STORE_NAME)
                     .index('status')
                     .getAll('pending');
        req.onsuccess = function (e) { resolve(e.target.result); };
        req.onerror   = function (e) { reject(e.target.error); };
      });
    });
  }

  function markOpSynced(id) { return _setStatus(id, 'synced'); }
  function markOpFailed(id) { return _setStatus(id, 'failed'); }

  function _setStatus(id, status) {
    return initDB().then(function (d) {
      return new Promise(function (resolve, reject) {
        const store = d.transaction(STORE_NAME, 'readwrite').objectStore(STORE_NAME);
        const req   = store.get(id);
        req.onsuccess = function (e) {
          const rec = e.target.result;
          if (rec) { rec.status = status; store.put(rec); }
          resolve();
        };
        req.onerror = function (e) { reject(e.target.error); };
      });
    });
  }

  function countPending() {
    return getPendingOps().then(function (ops) { return ops.length; });
  }

  // ── 3. Toast UI — non-blocking, auto-dismissing ───────────────────────────
  // Replaces the old full-width top banner that was blocking navigation.
  var _toast    = null;
  var _toastTmr = null;

  function getToast() {
    if (!_toast) {
      _toast = document.createElement('div');
      _toast.id = 'faida-net-toast';
      _toast.style.cssText =
        'position:fixed;bottom:4.5rem;left:50%;transform:translateX(-50%);' +
        'z-index:9998;width:min(310px,calc(100vw - 2rem));border-radius:10px;' +
        'padding:11px 16px;font-size:13px;font-weight:600;color:#fff;' +
        'box-shadow:0 4px 24px rgba(0,0,0,.22);display:none;' +
        'align-items:center;gap:8px;transition:opacity 0.3s ease;';
      document.body.appendChild(_toast);
    }
    return _toast;
  }

  function showToast(html, bg, autoDismissMs) {
    var t = getToast();
    clearTimeout(_toastTmr);
    t.style.background = bg;
    t.style.opacity    = '1';
    t.style.display    = 'flex';
    t.innerHTML        = html;
    if (autoDismissMs) {
      _toastTmr = setTimeout(function () {
        t.style.opacity = '0';
        setTimeout(function () { t.style.display = 'none'; }, 330);
      }, autoDismissMs);
    }
  }

  function showOfflineToast(pendingCount) {
    var extra = pendingCount > 0
      ? ' <span style="opacity:.75;font-size:11px">(' + pendingCount + ' en attente)</span>'
      : '';
    showToast('📡 Hors ligne' + extra, '#f5365c', 5500);
  }

  function showSavedOfflineToast() {
    showToast('💾 Sauvegardé hors ligne ✓', '#fb6340', 3500);
  }

  function showSyncingToast() {
    showToast('🔄 Synchronisation en cours…', '#2dce89', null);
  }

  function showSyncedToast(count) {
    showToast('✅ ' + count + ' enregistrement(s) synchronisé(s)', '#2dce89', 4000);
  }

  function showSyncErrorToast(failCount) {
    showToast('⚠️ ' + failCount + ' non synchronisé(s). Réessayez.', '#fb6340', 5000);
  }

  function hideToast() {
    var t = document.getElementById('faida-net-toast');
    if (t) { t.style.opacity = '0'; setTimeout(function () { t.style.display = 'none'; }, 330); }
    // Also keep the legacy banner hidden
    var old = document.getElementById('faida-offline-banner');
    if (old) old.style.display = 'none';
  }

  // ── 4. Online / Offline events ────────────────────────────────────────────
  window.addEventListener('offline', function () {
    countPending().then(function (n) { showOfflineToast(n); });
  });

  window.addEventListener('online', function () {
    showSyncingToast();
    if ('serviceWorker' in navigator && 'SyncManager' in window) {
      navigator.serviceWorker.ready
        .then(function (reg) { return reg.sync.register('faida-sync'); })
        .then(function () { pollForSyncCompletion(); })
        .catch(function () { manualSync(); });
    } else {
      manualSync();
    }
  });

  // ── 5. Sync ───────────────────────────────────────────────────────────────
  function manualSync() {
    getPendingOps().then(function (ops) {
      if (ops.length === 0) { hideToast(); return; }
      var synced = 0, failed = 0;
      var promises = ops.map(function (op) {
        return fetch(ENDPOINTS[op.type], {
          method:      'POST',
          headers:     { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
          body:        JSON.stringify(op.data),
          credentials: 'same-origin',
        })
        .then(function (r) {
          if (r.ok || r.status === 409) return markOpSynced(op.id).then(function () { synced++; });
          return markOpFailed(op.id).then(function () { failed++; });
        })
        .catch(function () { failed++; });
      });
      Promise.all(promises).then(function () {
        if (failed > 0)       showSyncErrorToast(failed);
        else if (synced > 0)  showSyncedToast(synced);
        else                  hideToast();
      });
    });
  }

  function pollForSyncCompletion() {
    var attempts = 0;
    var iv = setInterval(function () {
      attempts++;
      countPending().then(function (n) {
        if (n === 0)          { clearInterval(iv); showSyncedToast(1); }
        if (attempts >= 15)   { clearInterval(iv); manualSync(); }
      });
    }, 2000);
  }

  // ── 6. DOMContentLoaded — form intercept + load pending rows ─────────────
  document.addEventListener('DOMContentLoaded', function () {
    if (!navigator.onLine) {
      countPending().then(function (n) { if (n > 0) showOfflineToast(n); });
    }

    // Save original button texts before base.html's submit handler overwrites them
    document.querySelectorAll('button[type="submit"], input[type="submit"]').forEach(function (btn) {
      btn.dataset.origText = btn.innerHTML || btn.value || 'Enregistrer';
    });

    var path = window.location.pathname;
    if (path === '/vente_stock') {
      interceptSaleForm();
      loadPendingSales();
    } else if (path === '/achat_stock') {
      interceptStockPurchaseForm();
      loadPendingStocks();
    } else if (path === '/enregistrer_sortie') {
      interceptCashOutflowForm();
    }
  });

  function afterOfflineCapture(form) {
    if (typeof NProgress !== 'undefined') NProgress.done();
    form.reset();
    var btn = form.querySelector('button[type="submit"], input[type="submit"]');
    if (btn) { btn.disabled = false; btn.innerHTML = btn.dataset.origText || 'Enregistrer'; }
  }

  // ── Helper: current user name (from meta tag injected by base.html) ────────
  function currentUserName() {
    var m = document.querySelector('meta[name="faida-user"]');
    return m ? (m.getAttribute('content') || '—') : '—';
  }

  // ── Sale Form ─────────────────────────────────────────────────────────────
  function interceptSaleForm() {
    var form = document.querySelector('form[action*="vente_stock"]');
    if (!form) return;

    form.addEventListener('submit', function (e) {
      if (navigator.onLine) return;
      e.preventDefault();

      var data = collectSaleFormData(form);
      if (!data) return;
      data.local_id = generateUUID();

      queueOp('sale', data)
        .then(function () { return countPending(); })
        .then(function (n) {
          showOfflineToast(n);
          showSavedOfflineToast();
          renderPendingSaleRow(data);
          afterOfflineCapture(form);
        })
        .catch(function (err) {
          if (typeof NProgress !== 'undefined') NProgress.done();
          showLocalFlash('Erreur de sauvegarde: ' + err.message, 'danger');
        });
    });
  }

  function collectSaleFormData(form) {
    var fd    = new FormData(form);
    var items = [];
    var i     = 0;
    while (fd.get('sale_items-' + i + '-network') !== null) {
      var qty   = parseInt(fd.get('sale_items-' + i + '-quantity'));
      var price = parseFloat(fd.get('sale_items-' + i + '-price_per_unit_applied'));
      if (!isNaN(qty) && qty > 0) {
        items.push({
          network:               fd.get('sale_items-' + i + '-network'),
          quantity:              qty,
          price_per_unit_applied: isNaN(price) ? null : price,
        });
      }
      i++;
    }
    if (items.length === 0) { showLocalFlash('Ajoutez au moins un article.', 'warning'); return null; }

    // Resolve client display name at submit time
    var clientChoice = fd.get('client_choice');
    var clientName   = 'Client';
    if (clientChoice === 'new') {
      clientName = fd.get('new_client_name') || 'Nouveau client';
    } else {
      var sel = form.querySelector('[name="existing_client_id"]');
      if (sel && sel.options && sel.selectedIndex >= 0) {
        clientName = sel.options[sel.selectedIndex].text || 'Client';
      }
    }

    return {
      client_choice:      clientChoice,
      existing_client_id: fd.get('existing_client_id') || null,
      new_client_name:    fd.get('new_client_name') || null,
      _display_client:    clientName,          // local display only
      cash_paid:          parseFloat(fd.get('cash_paid')) || 0,
      sale_items:         items,
    };
  }

  // Render a pending sale row in the sales history table immediately
  function renderPendingSaleRow(data) {
    var tbody = document.getElementById('sales-history-tbody');
    if (!tbody) return;

    var now    = new Date();
    var ts     = now.toLocaleDateString('fr-CD') + ' ' + now.toLocaleTimeString('fr-CD', { hour: '2-digit', minute: '2-digit' });
    var seller = currentUserName();

    var itemsSummary = (data.sale_items || []).map(function (it) {
      return it.quantity + '×' + (it.network || '').toUpperCase();
    }).join(', ');

    var total = (data.sale_items || []).reduce(function (s, it) {
      return s + (it.quantity * (it.price_per_unit_applied || 0));
    }, 0);
    var debt = Math.max(0, total - (data.cash_paid || 0));

    var tr = document.createElement('tr');
    tr.setAttribute('data-pending-id', data.local_id);
    tr.style.cssText = 'background:#fffbea;border-left:3px solid #fb6340;';
    tr.innerHTML =
      '<td><span class="badge badge-warning" style="font-size:10px">⏳</span></td>' +
      '<td><strong>' + esc(data._display_client || 'Client') + '</strong></td>' +
      '<td>' + esc(seller) + '</td>' +
      '<td><small>' + esc(itemsSummary) + '</small></td>' +
      '<td>' + total.toFixed(2) + '</td>' +
      '<td>' + (data.cash_paid || 0).toFixed(2) + '</td>' +
      '<td>' + (debt > 0 ? '<span class="badge badge-danger">' + debt.toFixed(2) + '</span>' : '0.00') + '</td>' +
      '<td>' + ts + '</td>' +
      '<td><small class="text-warning font-weight-bold">Hors ligne</small></td>';

    // Insert before the first server-rendered row (or append if table is empty)
    var first = tbody.querySelector('tr:not([data-pending-id])');
    if (first) tbody.insertBefore(tr, first);
    else tbody.appendChild(tr);
  }

  // Load all pending sales from IndexedDB and render them on page load
  function loadPendingSales() {
    getPendingOps().then(function (ops) {
      ops.filter(function (op) { return op.type === 'sale'; })
         .forEach(function (op) { renderPendingSaleRow(op.data); });
    });
  }

  // ── Stock Purchase Form ───────────────────────────────────────────────────
  function interceptStockPurchaseForm() {
    var form = document.querySelector('form[action*="achat_stock"]');
    if (!form) return;

    form.addEventListener('submit', function (e) {
      if (navigator.onLine) return;
      e.preventDefault();

      var fd   = new FormData(form);
      var data = {
        local_id:                      generateUUID(),
        network:                       fd.get('network'),
        amount_purchased:              parseInt(fd.get('amount_purchased')),
        buying_price_choice:           fd.get('buying_price_choice'),
        custom_buying_price:           fd.get('custom_buying_price') || null,
        intended_selling_price_choice: fd.get('intended_selling_price_choice'),
        custom_intended_selling_price: fd.get('custom_intended_selling_price') || null,
      };

      if (!data.network || isNaN(data.amount_purchased) || data.amount_purchased < 1) {
        showLocalFlash('Veuillez remplir les champs obligatoires.', 'warning');
        return;
      }

      queueOp('stock_purchase', data)
        .then(function () { return countPending(); })
        .then(function (n) {
          showOfflineToast(n);
          showSavedOfflineToast();
          renderPendingStockRow(data);
          if (typeof $ !== 'undefined') $('#addStockPurchaseModal').modal('hide');
          afterOfflineCapture(form);
        })
        .catch(function (err) {
          if (typeof NProgress !== 'undefined') NProgress.done();
          showLocalFlash('Erreur: ' + err.message, 'danger');
        });
    });
  }

  function renderPendingStockRow(data) {
    var tbody = document.getElementById('stock-purchase-tbody');
    if (!tbody) return;

    var now    = new Date();
    var ts     = now.toLocaleDateString('fr-CD') + ' ' + now.toLocaleTimeString('fr-CD', { hour: '2-digit', minute: '2-digit' });
    var seller = currentUserName();

    var tr = document.createElement('tr');
    tr.setAttribute('data-pending-id', data.local_id);
    tr.style.cssText = 'background:#fffbea;border-left:3px solid #fb6340;';
    tr.innerHTML =
      '<td><span class="badge badge-warning" style="font-size:10px">⏳</span></td>' +
      '<td>' + esc((data.network || '').toUpperCase()) + '</td>' +
      '<td>' + (data.amount_purchased || 0) + ' unités</td>' +
      '<td>—</td>' +
      '<td>' + esc(seller) + '</td>' +
      '<td>' + ts + '</td>' +
      '<td><small class="text-warning font-weight-bold">Hors ligne</small></td>';

    var first = tbody.querySelector('tr:not([data-pending-id])');
    if (first) tbody.insertBefore(tr, first);
    else tbody.appendChild(tr);
  }

  function loadPendingStocks() {
    getPendingOps().then(function (ops) {
      ops.filter(function (op) { return op.type === 'stock_purchase'; })
         .forEach(function (op) { renderPendingStockRow(op.data); });
    });
  }

  // ── Cash Outflow Form ─────────────────────────────────────────────────────
  function interceptCashOutflowForm() {
    var form = document.querySelector('form[action*="enregistrer_sortie"]');
    if (!form) return;

    form.addEventListener('submit', function (e) {
      if (navigator.onLine) return;
      e.preventDefault();

      var fd     = new FormData(form);
      var amount = parseFloat(fd.get('amount'));

      if (!amount || amount <= 0) {
        showLocalFlash('Montant invalide.', 'warning');
        return;
      }

      var data = {
        local_id:    generateUUID(),
        amount,
        category:    fd.get('category'),
        description: fd.get('description') || '',
      };

      queueOp('cash_outflow', data)
        .then(function () { return countPending(); })
        .then(function (n) {
          showOfflineToast(n);
          showSavedOfflineToast();
          afterOfflineCapture(form);
        })
        .catch(function (err) {
          if (typeof NProgress !== 'undefined') NProgress.done();
          showLocalFlash('Erreur: ' + err.message, 'danger');
        });
    });
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  function esc(str) {
    return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function showLocalFlash(message, type) {
    var container = document.querySelector('.container-fluid') || document.body;
    var cls = { info: 'alert-info', success: 'alert-success', warning: 'alert-warning', danger: 'alert-danger' }[type] || 'alert-info';
    var div = document.createElement('div');
    div.className = 'alert ' + cls + ' alert-dismissible fade show mt-2';
    div.setAttribute('role', 'alert');
    div.innerHTML = message + '<button type="button" class="close" data-dismiss="alert"><span aria-hidden="true">&times;</span></button>';
    container.insertBefore(div, container.firstChild);
    setTimeout(function () {
      div.classList.remove('show');
      setTimeout(function () { if (div.parentNode) div.parentNode.removeChild(div); }, 300);
    }, 6000);
  }

  window._FaidaOffline = { getPendingOps, countPending, manualSync };
})();
