const CHINA_TIME_ZONE = 'Asia/Shanghai';
const CHINA_TIME_ZONE_OFFSET = '+08:00';
const BACKEND_NAIVE_DATETIME_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/;

const normalizeBackendDate = (value) => {
  if (!value) {
    return '';
  }

  const normalized = String(value).trim().replace(' ', 'T');
  if (!normalized) {
    return '';
  }

  const hasExplicitTimezone = normalized.endsWith('Z') || /[+-]\d{2}:?\d{2}$/.test(normalized);
  if (hasExplicitTimezone) {
    return normalized;
  }

  if (BACKEND_NAIVE_DATETIME_PATTERN.test(normalized)) {
    return `${normalized}${CHINA_TIME_ZONE_OFFSET}`;
  }

  return normalized;
};

export const parseBackendDate = (value) => {
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }

  const normalized = normalizeBackendDate(value);
  if (!normalized) {
    return null;
  }

  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
};

export const formatChinaDateTime = (value) => {
  const date = parseBackendDate(value);
  if (!date) {
    return '-';
  }

  return date.toLocaleString('zh-CN', {
    timeZone: CHINA_TIME_ZONE,
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
};

export const formatChinaDate = (value) => {
  const date = parseBackendDate(value);
  if (!date) {
    return '-';
  }

  return date.toLocaleDateString('zh-CN', {
    timeZone: CHINA_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });
};
