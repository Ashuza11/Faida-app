/**
 * Faida Offline Engine
 * ─────────────────────────────────────────────────────────────────────────
 * Responsibilities:
 *  1. Register the Service Worker
 *  2. Detect online/offline events → show/hide status banner
 *  3. Intercept form submits on key pages when offline
 *  4. Store pending ops in IndexedDB (faida_queue)
 *  5. Trigger sync when reconnected
 *  6. Update UI with sync results
 */

(function () {
  'use strict';

  // ── Constants ────────────────────────────────────────────────────────────
  const DB_NAME    = 'faida_offline';
  const DB_VERSION = 1;
  const STORE_NAME = 'faida_queue';

  // Endpoints for each operation type
  const ENDPOINTS = {
    sale:           '/api/v1/sales',
    stock_purchase: '/api/v1/stock-purchases',
    cash_outflow:   '/api/v1/cash-outflows',
  };

  // ── State ─────────────────────────────────────────────────────────────────
  let db = null;  // IndexedDB instance

  // ── 1. Service Worker Registration ───────────────────────────────────────
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js', { scope: '/' })
        .then(function (reg) {
          console.log('[Faida] SW registered, scope:', reg.scope);
        })
        .catch(function (err) {
          console.warn('[Faida] SW registration failed:', err);
        });
    });
  }

  // ── 2. IndexedDB Init ─────────────────────────────────────────────────────
  function initDB() {
    return new Promise(function (resolve, reject) {
      if (db) { resolve(db); return; }
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = function (e) {
        const database = e.target.result;
        if (!database.objectStoreNames.contains(STORE_NAME)) {
          const store = database.createObjectStore(STORE_NAME, { keyPath: 'id', autoIncrement: true });
          store.createIndex('status', 'status', { unique: false });
          store.createIndex('local_id', 'local_id', { unique: true });
        }
      };
      req.onsuccess = function (e) { db = e.target.result; resolve(db); };
      req.onerror   = function (e) { reject(e.target.error); };
    });
  }

  function queueOp(type, data) {
    return initDB().then(function (database) {
      return new Promise(function (resolve, reject) {
        const tx    = database.transaction(STORE_NAME, 'readwrite');
        const store = tx.objectStore(STORE_NAME);
        const record = {
          local_id:   data.local_id || generateUUID(),
          type:       type,
          status:     'pending',
          data:       data,
          queued_at:  new Date().toISOString(),
        };
        const req = store.add(record);
        req.onsuccess = function () { resolve(req.result); };
        req.onerror   = function (e) { reject(e.target.error); };
      });
    });
  }

  function getPendingOps() {
    return initDB().then(function (database) {
      return new Promise(function (resolve, reject) {
        const tx    = database.transaction(STORE_NAME, 'readonly');
        const store = tx.objectStore(STORE_NAME);
        const index = store.index('status');
        const req   = index.getAll('pending');
        req.onsuccess = function (e) { resolve(e.target.result); };
        req.onerror   = function (e) { reject(e.target.error); };
      });
    });
  }

  function markOpSynced(id) {
    return initDB().then(function (database) {
      return new Promise(function (resolve, reject) {
        const tx    = database.transaction(STORE_NAME, 'readwrite');
        const store = tx.objectStore(STORE_NAME);
        const req   = store.get(id);
        req.onsuccess = function (e) {
          const record = e.target.result;
          if (record) { record.status = 'synced'; store.put(record); }
          resolve();
        };
        req.onerror = function (e) { reject(e.target.error); };
      });
    });
  }

  function markOpFailed(id) {
    return initDB().then(function (database) {
      return new Promise(function (resolve, reject) {
        const tx    = database.transaction(STORE_NAME, 'readwrite');
        const store = tx.objectStore(STORE_NAME);
        const req   = store.get(id);
        req.onsuccess = function (e) {
          const record = e.target.result;
          if (record) { record.status = 'failed'; store.put(record); }
          resolve();
        };
        req.onerror = function (e) { reject(e.target.error); };
      });
    });
  }

  function countPending() {
    return getPendingOps().then(function (ops) { return ops.length; });
  }

  // ── 3. Banner UI ──────────────────────────────────────────────────────────
  function getBanner() { return document.getElementById('faida-offline-banner'); }

  function showOfflineBanner(pendingCount) {
    const banner = getBanner();
    if (!banner) return;
    const countEl = banner.querySelector('.faida-pending-count');
    if (countEl) countEl.textContent = pendingCount > 0 ? pendingCount + ' enregistrement(s) en attente' : '';
    banner.className = 'faida-banner faida-banner--offline';
    banner.style.display = 'block';
  }

  function showSyncingBanner() {
    const banner = getBanner();
    if (!banner) return;
    banner.className = 'faida-banner faida-banner--syncing';
    banner.style.display = 'block';
    banner.querySelector('.faida-banner-text').textContent = 'Connecté — Synchronisation en cours...';
    const countEl = banner.querySelector('.faida-pending-count');
    if (countEl) countEl.textContent = '';
  }

  function showSyncedBanner(count) {
    const banner = getBanner();
    if (!banner) return;
    banner.className = 'faida-banner faida-banner--synced';
    banner.style.display = 'block';
    banner.querySelector('.faida-banner-text').textContent = count + ' enregistrement(s) synchronisé(s) avec succès';
    const countEl = banner.querySelector('.faida-pending-count');
    if (countEl) countEl.textContent = '';
    setTimeout(function () { banner.style.display = 'none'; }, 4000);
  }

  function showSyncErrorBanner(failCount) {
    const banner = getBanner();
    if (!banner) return;
    banner.className = 'faida-banner faida-banner--error';
    banner.style.display = 'block';
    banner.querySelector('.faida-banner-text').textContent =
      failCount + ' enregistrement(s) n\'ont pas pu être synchronisés. Réessayez plus tard.';
    const countEl = banner.querySelector('.faida-pending-count');
    if (countEl) countEl.textContent = '';
  }

  function hideBanner() {
    const banner = getBanner();
    if (banner) banner.style.display = 'none';
  }

  function updateBannerForStatus() {
    if (!navigator.onLine) {
      countPending().then(function (count) { showOfflineBanner(count); });
    } else {
      hideBanner();
    }
  }

  // ── 4. Online/Offline event listeners ─────────────────────────────────────
  window.addEventListener('offline', function () {
    countPending().then(function (count) { showOfflineBanner(count); });
  });

  window.addEventListener('online', function () {
    showSyncingBanner();
    // Try Background Sync first; fall back to manual sync
    if ('serviceWorker' in navigator && 'SyncManager' in window) {
      navigator.serviceWorker.ready.then(function (reg) {
        return reg.sync.register('faida-sync');
      }).then(function () {
        // Background sync registered — SW will handle it
        // Poll for completion
        pollForSyncCompletion();
      }).catch(function () {
        // SyncManager failed — do manual sync
        manualSync();
      });
    } else {
      manualSync();
    }
  });

  // ── 5. Manual Sync (fallback when Background Sync not available) ──────────
  function manualSync() {
    getPendingOps().then(function (ops) {
      if (ops.length === 0) { hideBanner(); return; }

      var syncedCount = 0;
      var failedCount = 0;
      var promises = ops.map(function (op) {
        return fetch(ENDPOINTS[op.type], {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
          },
          body: JSON.stringify(op.data),
          credentials: 'same-origin',
        })
        .then(function (resp) {
          if (resp.ok || resp.status === 409) {
            return markOpSynced(op.id).then(function () { syncedCount++; });
          } else {
            return markOpFailed(op.id).then(function () { failedCount++; });
          }
        })
        .catch(function () {
          failedCount++;
        });
      });

      Promise.all(promises).then(function () {
        if (failedCount > 0) {
          showSyncErrorBanner(failedCount);
        } else if (syncedCount > 0) {
          showSyncedBanner(syncedCount);
        } else {
          hideBanner();
        }
      });
    });
  }

  // Poll every 2s for up to 30s to see if background sync cleared the queue
  function pollForSyncCompletion() {
    var attempts = 0;
    var maxAttempts = 15;
    var interval = setInterval(function () {
      attempts++;
      countPending().then(function (count) {
        if (count === 0) {
          clearInterval(interval);
          showSyncedBanner(1); // Approximate — SW synced at least 1
        }
        if (attempts >= maxAttempts) {
          clearInterval(interval);
          // Fall back to manual sync to get exact count and status
          manualSync();
        }
      });
    }, 2000);
  }

  // ── 6. Form Interception ──────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', function () {
    // Initial banner state
    updateBannerForStatus();

    // Pre-save all submit button texts NOW, before base.html's submit handler
    // replaces them with "En cours…". We store them as data-orig-text attributes.
    document.querySelectorAll('button[type="submit"], input[type="submit"]').forEach(function (btn) {
      btn.dataset.origText = btn.innerHTML || btn.value || 'Enregistrer';
    });

    // Detect current page
    var path = window.location.pathname;

    if (path === '/vente_stock') {
      interceptSaleForm();
    } else if (path === '/achat_stock') {
      interceptStockPurchaseForm();
    } else if (path === '/enregistrer_sortie') {
      interceptCashOutflowForm();
    }
  });

  /**
   * Call this after successfully intercepting a form offline.
   * Stops the NProgress bar (started by base.html's submit listener),
   * resets the form, and restores the submit button.
   */
  function afterOfflineCapture(form) {
    // Stop NProgress bar — it was started by base.html's document submit listener
    if (typeof NProgress !== 'undefined') NProgress.done();

    form.reset();

    var btn = form.querySelector('button[type="submit"], input[type="submit"]');
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = btn.dataset.origText || 'Enregistrer';
    }
  }

  // ── Sale Form ─────────────────────────────────────────────────────────────
  function interceptSaleForm() {
    var form = document.querySelector('form[action*="vente_stock"]');
    if (!form) return;

    form.addEventListener('submit', function (e) {
      if (navigator.onLine) return; // Normal submit
      e.preventDefault();

      var data = collectSaleFormData(form);
      if (!data) return; // Validation failed offline — let user fix

      data.local_id = generateUUID();
      queueOp('sale', data).then(function () {
        return countPending();
      }).then(function (count) {
        showOfflineBanner(count);
        showLocalFlash('Vente sauvegardée localement — sera synchronisée dès la reconnexion.', 'info');
        afterOfflineCapture(form);
      }).catch(function (err) {
        if (typeof NProgress !== 'undefined') NProgress.done();
        showLocalFlash('Erreur de sauvegarde locale: ' + err.message, 'danger');
      });
    });
  }

  function collectSaleFormData(form) {
    var fd = new FormData(form);
    var items = [];
    var i = 0;
    while (fd.get('sale_items-' + i + '-network') !== null) {
      var qty = parseInt(fd.get('sale_items-' + i + '-quantity'));
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
    if (items.length === 0) {
      showLocalFlash('Ajoutez au moins un article.', 'warning');
      return null;
    }
    return {
      client_choice:    fd.get('client_choice'),
      existing_client_id: fd.get('existing_client_id') || null,
      new_client_name:  fd.get('new_client_name') || null,
      cash_paid:        parseFloat(fd.get('cash_paid')) || 0,
      sale_items:       items,
    };
  }

  // ── Stock Purchase Form ───────────────────────────────────────────────────
  function interceptStockPurchaseForm() {
    // The form is inside a modal
    var form = document.querySelector('form[action*="achat_stock"]');
    if (!form) return;

    form.addEventListener('submit', function (e) {
      if (navigator.onLine) return;
      e.preventDefault();

      var fd = new FormData(form);
      var data = {
        local_id:                    generateUUID(),
        network:                     fd.get('network'),
        amount_purchased:            parseInt(fd.get('amount_purchased')),
        buying_price_choice:         fd.get('buying_price_choice'),
        custom_buying_price:         fd.get('custom_buying_price') || null,
        intended_selling_price_choice: fd.get('intended_selling_price_choice'),
        custom_intended_selling_price: fd.get('custom_intended_selling_price') || null,
      };

      if (!data.network || isNaN(data.amount_purchased) || data.amount_purchased < 1) {
        showLocalFlash('Veuillez remplir les champs obligatoires.', 'warning');
        return;
      }

      queueOp('stock_purchase', data).then(function () {
        return countPending();
      }).then(function (count) {
        showOfflineBanner(count);
        showLocalFlash('Achat sauvegardé localement — sera synchronisé dès la reconnexion.', 'info');
        if (typeof $ !== 'undefined') $('#addStockPurchaseModal').modal('hide');
        afterOfflineCapture(form);
      }).catch(function (err) {
        if (typeof NProgress !== 'undefined') NProgress.done();
        showLocalFlash('Erreur de sauvegarde locale: ' + err.message, 'danger');
      });
    });
  }

  // ── Cash Outflow Form ─────────────────────────────────────────────────────
  function interceptCashOutflowForm() {
    var form = document.querySelector('form[action*="enregistrer_sortie"]');
    if (!form) return;

    form.addEventListener('submit', function (e) {
      if (navigator.onLine) return;
      e.preventDefault();

      var fd = new FormData(form);
      var amount = parseFloat(fd.get('amount'));

      if (!amount || amount <= 0) {
        showLocalFlash('Veuillez entrer un montant valide.', 'warning');
        return;
      }

      var data = {
        local_id:    generateUUID(),
        amount:      amount,
        category:    fd.get('category'),
        description: fd.get('description') || '',
      };

      queueOp('cash_outflow', data).then(function () {
        return countPending();
      }).then(function (count) {
        showOfflineBanner(count);
        showLocalFlash('Sortie cash sauvegardée localement — sera synchronisée dès la reconnexion.', 'info');
        afterOfflineCapture(form);
      }).catch(function (err) {
        if (typeof NProgress !== 'undefined') NProgress.done();
        showLocalFlash('Erreur de sauvegarde locale: ' + err.message, 'danger');
      });
    });
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      var v = c === 'x' ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  function showLocalFlash(message, type) {
    var container = document.querySelector('.container-fluid');
    if (!container) container = document.body;

    var alertClass = {
      info: 'alert-info',
      success: 'alert-success',
      warning: 'alert-warning',
      danger: 'alert-danger',
    }[type] || 'alert-info';

    var div = document.createElement('div');
    div.className = 'alert ' + alertClass + ' alert-dismissible fade show mt-2';
    div.setAttribute('role', 'alert');
    div.innerHTML =
      message +
      '<button type="button" class="close" data-dismiss="alert" aria-label="Fermer">' +
      '<span aria-hidden="true">&times;</span></button>';

    // Insert at the top of the container
    container.insertBefore(div, container.firstChild);

    // Auto-hide after 6s
    setTimeout(function () {
      if (div.parentNode) {
        div.classList.remove('show');
        setTimeout(function () { if (div.parentNode) div.parentNode.removeChild(div); }, 300);
      }
    }, 6000);
  }

  // Expose for debugging
  window._FaidaOffline = {
    getPendingOps: getPendingOps,
    countPending:  countPending,
    manualSync:    manualSync,
  };
})();
