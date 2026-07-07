const GANKAIGC_RESULT_EVENT = 'GANKAIGC_ZHUQUE_RESULT';

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function visible(el) {
  if (!el) return false;
  const rect = el.getBoundingClientRect();
  const style = window.getComputedStyle(el);
  return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
}

function visibleInViewport(el) {
  if (!visible(el)) return false;
  const rect = el.getBoundingClientRect();
  const vw = window.innerWidth || document.documentElement.clientWidth;
  const vh = window.innerHeight || document.documentElement.clientHeight;
  return rect.width >= 20 && rect.height >= 20 && rect.bottom > 0 && rect.right > 0 && rect.top < vh && rect.left < vw;
}

function detectCaptchaOrLogin() {
  const captchaFrames = [...document.querySelectorAll('iframe[src*="captcha"], iframe[src*="tcaptcha"], iframe[src*="gtimg"]')]
    .filter(visibleInViewport);
  const visibleCaptchaText = [...document.querySelectorAll('button, a, span, div, p')]
    .filter(visibleInViewport)
    .map((el) => (el.textContent || '').trim())
    .filter(Boolean)
    .some((text) => /请完成安全验证|拖动.*滑块|滑块验证|选择.*相似|Choose all similar|Verification Code/i.test(text));
  const hasCaptcha = captchaFrames.length > 0 || visibleCaptchaText;
  if (hasCaptcha) {
    return { manual_required: true, error_code: 'zhuque_captcha_required', message: '请在本机朱雀页面完成验证码' };
  }
  const loginVisible = [...document.querySelectorAll('button, a, span, div')]
    .filter(visible)
    .some((el) => /^(登录|扫码登录|微信登录|Login|Sign in)$/i.test((el.textContent || '').trim()));
  if (loginVisible) {
    return { manual_required: true, error_code: 'zhuque_not_logged_in', message: '请先在本机朱雀页面登录朱雀' };
  }
  return null;
}

function findInput() {
  const selectors = [
    'textarea',
    '[contenteditable="true"]',
    '.el-textarea__inner',
    '.input textarea',
    '.detect-input textarea'
  ];
  for (const selector of selectors) {
    const el = [...document.querySelectorAll(selector)].find(visible);
    if (el) return el;
  }
  return null;
}

function setInputText(el, text) {
  el.focus();
  if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
    el.value = text;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return;
  }
  el.textContent = text;
  el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text }));
}

function findClearButton() {
  return [...document.querySelectorAll('button, a')]
    .filter(visible)
    .find((el) => /清空|Clear/i.test(el.textContent || ''));
}

function findDetectButton() {
  return [...document.querySelectorAll('button, a')]
    .filter(visible)
    .find((el) => /立即检测|开始检测|重新检测|Detect|Check/i.test(el.textContent || ''));
}

function parsePercent(text) {
  const match = String(text || '').match(/(\d+(?:\.\d+)?)\s*%/);
  return match ? Number(match[1]) : null;
}

function domResultFallback() {
  const resultNode = [...document.querySelectorAll('.card-right, .rst')]
    .filter(visible)
    .find((el) => {
      const text = el.innerText || el.textContent || '';
      if (/检测中|立即检测|上传|清空|示例一|示例二|示例三|示例四/.test(text)) return false;
      return /人工特征|AI特征|疑似AI|人工创作|AI生成|疑似/.test(text);
    });
  if (!resultNode) return null;
  const resultText = resultNode.innerText || resultNode.textContent || '';
  const percents = [...resultText.matchAll(/(\d+(?:\.\d+)?)\s*%/g)].map((m) => Number(m[1]));
  if (percents.length >= 3) {
    return {
      success: true,
      source: 'browser_agent_dom',
      // 朱雀右侧图例顺序：人工特征、疑似AI、AI特征；GankAIGC：AI、人工、疑似。
      rate: percents[2],
      risk_rate: Math.max(percents[2] || 0, percents[1] || 0),
      rate_label: resultText.split(/\n/).find((line) => /人工创作|AI生成|疑似|人工特征|AI特征/.test(line)) || '朱雀页面检测结果',
      labels_ratio: { '0': (percents[2] || 0) / 100, '1': (percents[0] || 0) / 100, '2': (percents[1] || 0) / 100 },
      segment_labels: [],
      raw_payload: { rate: percents[2], labelsRatio: { '0': (percents[0] || 0) / 100, '1': (percents[2] || 0) / 100, '2': (percents[1] || 0) / 100 }, result_text: resultText.slice(0, 500) }
    };
  }
  return null;
}

function normalizeScore(value) {
  const score = Number(value);
  if (!Number.isFinite(score)) return null;
  const percent = score <= 1 ? score * 100 : score;
  if (percent < 0 || percent > 100) return null;
  return percent;
}

function validSegmentLabels(segmentLabels) {
  if (!Array.isArray(segmentLabels)) return [];
  return segmentLabels.filter((item) => {
    const label = Number(item?.label);
    const span = Array.isArray(item?.position) ? Number(item.position[1]) : 0;
    return [0, 1, 2].includes(label) && Number.isFinite(span) && span > 0 && typeof item?.text === 'string' && item.text.trim().length > 0;
  });
}

function ratioFromSegmentLabels(segmentLabels) {
  const validLabels = validSegmentLabels(segmentLabels);
  if (!validLabels.length) return null;
  const raw = { 0: 0, 1: 0, 2: 0 };
  for (const item of validLabels) {
    const label = Number(item.label);
    const span = Number(item.position[1]);
    raw[label] += span;
  }
  const total = raw[0] + raw[1] + raw[2];
  if (!total) return null;
  return {
    // 朱雀当前页面：0=人工, 1=AI, 2=疑似；GankAIGC：0=AI, 1=人工, 2=疑似。
    '0': raw[1] / total,
    '1': raw[0] / total,
    '2': raw[2] / total
  };
}

function terminalPayloadFromInjected(payload) {
  if (!payload || typeof payload !== 'object') return null;
  const data = payload.data || payload.result || payload.value || payload;
  if (!data || typeof data !== 'object') return null;
  const segmentLabels = validSegmentLabels(data.segment_labels || data.segmentLabels || []);
  const segmentRatio = ratioFromSegmentLabels(segmentLabels);
  const rawLabels = data.labels_ratio || data.labelsRatio || null;
  const aiRate = normalizeScore(data.rate ?? data.confidence ?? data.ai_generated);
  const labelsRatio = segmentRatio || rawLabels || (aiRate !== null ? { '0': aiRate / 100, '1': Math.max(0, 1 - aiRate / 100), '2': 0 } : {});
  const hasRate = aiRate !== null || Object.keys(labelsRatio).length > 0 || segmentLabels.length > 0;
  if (!hasRate) return null;
  const normalizedRate = aiRate !== null ? aiRate : (labelsRatio['0'] || 0) * 100;
  return {
    success: true,
    source: 'browser_agent_page',
    raw_payload: data,
    rate: Number(normalizedRate.toFixed(2)),
    risk_rate: Number(Math.max(labelsRatio['0'] || 0, labelsRatio['2'] || 0) * 100).toFixed ? Number((Math.max(labelsRatio['0'] || 0, labelsRatio['2'] || 0) * 100).toFixed(2)) : normalizedRate,
    rate_label: data.rateLabel || data.rate_label || '朱雀页面检测结果',
    labels_ratio: labelsRatio,
    segment_labels: segmentLabels
  };
}

function requestInjectedSnapshot() {
  return new Promise((resolve) => {
    const requestId = `${Date.now()}-${Math.random()}`;
    const timer = setTimeout(() => {
      window.removeEventListener('message', listener);
      resolve(null);
    }, 1000);
    function listener(event) {
      if (event.source !== window || event.data?.type !== 'GANKAIGC_ZHUQUE_SNAPSHOT_RESPONSE') return;
      if (event.data.requestId !== requestId) return;
      clearTimeout(timer);
      window.removeEventListener('message', listener);
      const payload = (event.data.payloads || [])
        .map((item) => terminalPayloadFromInjected(item.value || item))
        .find(Boolean);
      resolve(payload || null);
    }
    window.addEventListener('message', listener);
    window.postMessage({ type: 'GANKAIGC_ZHUQUE_SNAPSHOT_REQUEST', requestId }, '*');
  });
}

async function waitForResult(timeoutMs) {
  let networkResult = null;
  const listener = (event) => {
    if (event.source !== window || event.data?.type !== GANKAIGC_RESULT_EVENT) return;
    networkResult = terminalPayloadFromInjected(event.data.payload);
  };
  window.addEventListener('message', listener);
  try {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      if (networkResult) return networkResult;
      const snapshotResult = await requestInjectedSnapshot();
      if (snapshotResult) return snapshotResult;
      const domResult = domResultFallback();
      if (domResult) return domResult;
      const manual = detectCaptchaOrLogin();
      if (manual) return manual;
      await sleep(1000);
    }
    return { success: false, error_code: 'zhuque_browser_agent_timeout', message: '等待朱雀检测结果超时', retryable: true };
  } finally {
    window.removeEventListener('message', listener);
  }
}

async function runZhuqueDetect(job) {
  await sleep(1000);
  const manualBefore = detectCaptchaOrLogin();
  if (manualBefore) return manualBefore;

  const clearButton = findClearButton();
  if (clearButton) {
    clearButton.click();
    await sleep(300);
  }

  const input = findInput();
  if (!input) {
    return { success: false, error_code: 'zhuque_input_not_found', message: '未找到朱雀检测输入框', retryable: true };
  }
  setInputText(input, job.text || '');
  await sleep(500);

  const detectButton = findDetectButton();
  if (!detectButton) {
    return { success: false, error_code: 'zhuque_detect_button_not_found', message: '未找到朱雀立即检测按钮', retryable: true };
  }
  detectButton.click();

  const timeoutMs = Math.max(30000, Number(job.timeout_seconds || 180) * 1000);
  return await waitForResult(timeoutMs);
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== 'GANKAIGC_ZHUQUE_DETECT') return false;
  runZhuqueDetect(message.job || {})
    .then((result) => {
      if (result?.manual_required) {
        sendResponse({ success: false, manual_required: true, error_code: result.error_code, message: result.message, metadata: result });
        return;
      }
      if (!result?.success) {
        sendResponse(result || { success: false, message: '朱雀检测失败' });
        return;
      }
      sendResponse({ success: true, result });
    })
    .catch((error) => sendResponse({ success: false, error_code: 'zhuque_browser_agent_exception', message: String(error.message || error), retryable: true }));
  return true;
});
