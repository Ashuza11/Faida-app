/** User-friendly PWA installation prompt for supported mobile browsers. */
(function () {
  'use strict';

  var deferredInstallPrompt = null;
  var backdrop = document.getElementById('faida-install-backdrop');
  var installButton = document.getElementById('faida-install-button');
  var laterButton = document.getElementById('faida-install-later');
  var closeButton = document.getElementById('faida-install-close');
  var help = document.getElementById('faida-install-help');
  var dismissalKey = 'faida-install-dismissed';

  if (!backdrop || !installButton || !laterButton || !closeButton || !help) return;

  function isInstalled() {
    return window.matchMedia('(display-mode: standalone)').matches
      || window.navigator.standalone === true
      || document.referrer.indexOf('android-app://') === 0;
  }

  function wasDismissedThisSession() {
    try {
      return window.sessionStorage.getItem(dismissalKey) === '1';
    } catch (error) {
      return false;
    }
  }

  function rememberDismissal() {
    try {
      window.sessionStorage.setItem(dismissalKey, '1');
    } catch (error) {
      // Installation still works when storage is disabled.
    }
  }

  function showPrompt() {
    if (isInstalled() || wasDismissedThisSession()) return;
    backdrop.classList.add('is-visible');
    backdrop.setAttribute('aria-hidden', 'false');
    window.setTimeout(function () { installButton.focus(); }, 50);
  }

  function hidePrompt(remember) {
    backdrop.classList.remove('is-visible');
    backdrop.setAttribute('aria-hidden', 'true');
    if (remember) rememberDismissal();
  }

  function showInstructions(message) {
    help.textContent = message;
    help.hidden = false;
    installButton.textContent = 'Compris';
    installButton.dataset.instructionsOnly = 'true';
    showPrompt();
  }

  window.addEventListener('beforeinstallprompt', function (event) {
    event.preventDefault();
    deferredInstallPrompt = event;
    help.hidden = true;
    installButton.textContent = 'Installer';
    delete installButton.dataset.instructionsOnly;
    window.setTimeout(showPrompt, 700);
  });

  installButton.addEventListener('click', function () {
    if (installButton.dataset.instructionsOnly === 'true') {
      hidePrompt(true);
      return;
    }
    if (!deferredInstallPrompt) return;

    hidePrompt(false);
    deferredInstallPrompt.prompt();
    deferredInstallPrompt.userChoice.then(function (choice) {
      if (choice.outcome !== 'accepted') rememberDismissal();
      deferredInstallPrompt = null;
    });
  });

  laterButton.addEventListener('click', function () { hidePrompt(true); });
  closeButton.addEventListener('click', function () { hidePrompt(true); });
  backdrop.addEventListener('click', function (event) {
    if (event.target === backdrop) hidePrompt(true);
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && backdrop.classList.contains('is-visible')) {
      hidePrompt(true);
    }
  });

  window.addEventListener('appinstalled', function () {
    deferredInstallPrompt = null;
    hidePrompt(false);
  });

  window.addEventListener('load', function () {
    if (isInstalled() || wasDismissedThisSession()) return;
    var userAgent = window.navigator.userAgent || '';
    var isIOS = /iphone|ipad|ipod/i.test(userAgent);
    var isAndroid = /android/i.test(userAgent);

    if (isIOS) {
      window.setTimeout(function () {
        showInstructions("Touchez Partager, puis « Sur l'écran d'accueil ».");
      }, 900);
      return;
    }

    // Some Android browsers do not expose beforeinstallprompt. Give Chrome a
    // moment to fire it, then offer the browser-menu instructions as fallback.
    if (isAndroid) {
      window.setTimeout(function () {
        if (!deferredInstallPrompt && !wasDismissedThisSession()) {
          showInstructions("Ouvrez le menu du navigateur, puis choisissez « Installer l'application ».");
        }
      }, 3000);
    }
  });
})();
