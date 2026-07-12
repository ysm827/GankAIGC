(function exposeZhuqueQuota(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.GankAIGCZhuqueQuota = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, () => {
  const QUOTA_KEYS = [
    'aiGenTxtRemainingCount',
    'availableUses',
    'available_uses',
    'remainingUses',
    'remaining_uses',
    'quotaText',
    'quota_text',
    'submitButtonText',
    'button_text',
    'remaining',
    'available',
    'quota',
    'left'
  ];
  const WRAPPER_KEYS = [
    'data',
    'result',
    'payload',
    'value',
    'props',
    'setupState',
    'ctx',
    '$data'
  ];

  function parseRemainingUses(value) {
    if (value === null || value === undefined || typeof value === 'boolean') {
      return undefined;
    }
    if (typeof value === 'number') {
      return Number.isFinite(value) && value >= 0 ? Math.trunc(value) : undefined;
    }
    const text = String(value).replace(/\s+/g, ' ').trim();
    if (!text || /(^|\D)-1(\D|$)|unknown|unavailable|检测后同步|未知|不可用/i.test(text)) {
      return undefined;
    }
    const numeric = Number(text);
    if (Number.isFinite(numeric)) {
      return numeric >= 0 ? Math.trunc(numeric) : undefined;
    }
    const patterns = [
      /(?:今日)?剩余\s*(\d+)\s*次/i,
      /还可(?:检测)?\s*(\d+)\s*次/i,
      /可用\s*(\d+)\s*次/i,
      /Detect\s*now\s*\(\s*(\d+)\s*left\s*\)/i,
      /(\d+)\s*(?:left|uses?|次)/i,
      /(?:left|uses?|remaining|available|quota)[^\d]{0,16}(\d+)/i,
      /(?:Detect now|立即检测)[^\d]{0,16}(\d+)/i
    ];
    const match = patterns.map((pattern) => text.match(pattern)).find(Boolean);
    return match ? Number(match[1]) : undefined;
  }

  function extractRemainingUses(value, depth = 0, seen = new Set()) {
    if (value === null || value === undefined || depth > 5) {
      return undefined;
    }
    if (typeof value !== 'object') {
      return parseRemainingUses(value);
    }
    if (seen.has(value)) {
      return undefined;
    }
    seen.add(value);

    if (Array.isArray(value)) {
      for (const item of value) {
        const remaining = extractRemainingUses(item, depth + 1, seen);
        if (remaining !== undefined) return remaining;
      }
      return undefined;
    }

    for (const key of QUOTA_KEYS) {
      if (!Object.prototype.hasOwnProperty.call(value, key)) continue;
      const remaining = extractRemainingUses(value[key], depth + 1, seen);
      if (remaining !== undefined) return remaining;
    }
    for (const key of WRAPPER_KEYS) {
      if (!Object.prototype.hasOwnProperty.call(value, key)) continue;
      const remaining = extractRemainingUses(value[key], depth + 1, seen);
      if (remaining !== undefined) return remaining;
    }
    return undefined;
  }

  return { parseRemainingUses, extractRemainingUses };
});
