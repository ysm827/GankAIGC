const test = require('node:test');
const assert = require('node:assert/strict');

const { parseRemainingUses, extractRemainingUses } = require('../zhuque-quota.js');

test('parses Zhuque quota text without treating unknown as a number', () => {
  assert.equal(parseRemainingUses('Detect now(18 left)'), 18);
  assert.equal(parseRemainingUses('今日剩余 7 次'), 7);
  assert.equal(parseRemainingUses('remaining_uses: -1'), undefined);
});

test('extracts quota from terminal payload and nested Vue refs', () => {
  assert.equal(extractRemainingUses({ data: { availableUses: 16 } }), 16);
  assert.equal(
    extractRemainingUses({ setupState: { aiGenTxtRemainingCount: { value: 12 } } }),
    12
  );
});

test('does not mistake unrelated remaining request counters for Zhuque quota', () => {
  assert.equal(extractRemainingUses({ remainingRequests: 3, rate: 42 }), undefined);
});
