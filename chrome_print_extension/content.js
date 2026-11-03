/**
 * Forwards betting-page postMessage wakes to the extension service worker.
 * Only messages with source "smartwagers-print" are accepted.
 */
(function () {
  'use strict';

  if (window.__smartwagersPrintBridge) return;
  window.__smartwagersPrintBridge = true;

  window.addEventListener('message', (event) => {
    if (event.origin !== window.location.origin) return;
    const data = event.data;
    if (!data || data.source !== 'smartwagers-print') return;
    if (data.type !== 'job-queued') return;
    try {
      chrome.runtime.sendMessage({ type: 'job-queued' }, () => {
        void chrome.runtime.lastError;
      });
    } catch {
      // Extension context may be invalidated during reload.
    }
  });
})();
