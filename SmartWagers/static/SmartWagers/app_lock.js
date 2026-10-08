(function () {
  var STYLE_ID = 'app-lock-style';

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = [
      '#app-lock-banner {',
      '  position: sticky;',
      '  top: 0;',
      '  z-index: 10000;',
      '  background: #7b241c;',
      '  color: #fff;',
      '  text-align: center;',
      '  padding: 10px 16px;',
      '  font-weight: 700;',
      '}',
      'body.app-locked button:not(.nav-logout-button):not([data-lock-allow]),',
      'body.app-locked .button,',
      'body.app-locked input[type="submit"]:not([data-lock-allow]) {',
      '  pointer-events: none;',
      '  opacity: 0.55;',
      '}',
      'body.app-locked form[action$="logout"] button,',
      'body.app-locked #st-master-lock-panel button,',
      'body.app-locked #st-master-lock-panel input {',
      '  pointer-events: auto;',
      '  opacity: 1;',
      '}',
    ].join('\n');
    document.head.appendChild(style);
  }

  function bannerText(reasons) {
    var list = reasons || [];
    if (list.indexOf('manual') !== -1 && list.indexOf('expired') !== -1) {
      return 'Operations are locked and the license period has expired. Viewing still works. A superuser can unlock and renew from Settings or the master lock page.';
    }
    if (list.indexOf('manual') !== -1) {
      return 'Operations are locked. Viewing still works. A superuser can unlock from Settings or the master lock page.';
    }
    if (list.indexOf('expired') !== -1) {
      return 'The license period has expired. Viewing still works. Renew the master lock to continue operations.';
    }
    return 'Operations are locked. Viewing still works.';
  }

  window.applyAppLockState = function (data) {
    if (!data || !('app_locked' in data) && !('locked' in data)) return;
    var locked = Boolean(data.app_locked || data.locked);
    ensureStyle();
    var banner = document.getElementById('app-lock-banner');
    if (!locked) {
      document.body.classList.remove('app-locked');
      if (banner) banner.remove();
      return;
    }
    document.body.classList.add('app-locked');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'app-lock-banner';
      banner.setAttribute('role', 'status');
      document.body.prepend(banner);
    }
    banner.textContent = bannerText(data.lock_reasons);
  };

  document.addEventListener('DOMContentLoaded', function () {
    fetch('/master-lock/status/', {
      headers: { 'Accept': 'application/json' },
      credentials: 'same-origin',
    }).then(function (response) {
      return response.json();
    }).then(function (data) {
      window.applyAppLockState({
        app_locked: Boolean(data.locked),
        lock_reasons: data.lock_reasons || [],
      });
    }).catch(function () {});
  });
})();
