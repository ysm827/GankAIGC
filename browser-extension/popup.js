const $ = (id) => document.getElementById(id);

function setMessage(text, isError = false) {
  const node = $('message');
  node.textContent = text || '';
  node.className = isError ? 'message error' : 'message';
}

async function send(message) {
  return await chrome.runtime.sendMessage(message);
}

async function refreshStatus() {
  const status = await send({ type: 'GET_STATUS' });
  $('serverUrl').value = status.serverUrl || 'https://ga.mumubuku.top';
  $('pairingCode').value = status.pairingCode || '';
  $('agentName').value = status.agentName || 'Chrome on Windows';
  $('agentId').textContent = status.agentId || '--';
  $('statusText').textContent = status.paired ? '已配对' : '未配对';
}

async function saveDraft() {
  await send({
    type: 'SAVE_POPUP_DRAFT',
    payload: {
      serverUrl: $('serverUrl').value,
      pairingCode: $('pairingCode').value,
      agentName: $('agentName').value
    }
  });
}

['serverUrl', 'pairingCode', 'agentName'].forEach((id) => {
  $(id).addEventListener('input', () => saveDraft().catch(() => undefined));
});

$('pairButton').addEventListener('click', async () => {
  setMessage('正在配对...');
  try {
    await saveDraft();
    const response = await send({
      type: 'CLAIM_PAIRING',
      payload: {
        serverUrl: $('serverUrl').value,
        pairingCode: $('pairingCode').value,
        agentName: $('agentName').value
      }
    });
    if (!response?.ok) throw new Error(response?.message || '配对失败');
    setMessage(`配对成功：${response.agentId}`);
    await refreshStatus();
  } catch (error) {
    setMessage(error.message || String(error), true);
  }
});

$('forgetButton').addEventListener('click', async () => {
  await send({ type: 'FORGET_AGENT' });
  setMessage('已清除本机配对');
  await refreshStatus();
});

refreshStatus().catch((error) => setMessage(error.message || String(error), true));
