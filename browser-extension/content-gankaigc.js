const PAGE_SOURCE = 'GANKAIGC_PAGE';
const EXTENSION_SOURCE = 'GANKAIGC_EXTENSION';

window.addEventListener('message', (event) => {
  if (event.source !== window) return;
  const data = event.data || {};
  if (data.source !== PAGE_SOURCE || data.type !== 'GANKAIGC_SYNC_ZHUQUE_STATUS') return;

  const requestId = data.requestId || '';
  chrome.runtime.sendMessage({
    type: 'SYNC_ZHUQUE_STATUS',
    payload: { focus: Boolean(data.focus) }
  }, (response) => {
    window.postMessage({
      source: EXTENSION_SOURCE,
      type: 'GANKAIGC_SYNC_ZHUQUE_STATUS_RESULT',
      requestId,
      response: response || { ok: false, message: '插件未返回同步结果' }
    }, window.location.origin);
  });
});
