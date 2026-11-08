const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app.js', 'utf8');
function fn(name) {
    const start = source.indexOf('function ' + name + '(');
    assert.ok(start >= 0, name);
    return source.slice(start, source.indexOf('\n}\n', start) + 3);
}
const escapeHtml = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
const c = vm.createContext({
    wdState: {info: {limits: {max: 123}}, method: 'stars'},
    wdGo: step => {c.step = step;},
    wdShowError: message => {c.error = message;},
    wdSumRow: (key, value) => key + ':' + value,
    wdUsd: value => value + ' Stars',
    wdNum: String, fmtNum: String, escapeHtml,
    document: {getElementById: () => ({value: '49'})},
    wdParseInput: Number,
    depositState: {tonkeeperInfo: {wallet: '<wallet>', comment: '<comment>', tonAmount: '1.1', amount: 100, tonDeeplink: 'https://app.tonkeeper.com/transfer/wallet'}},
});
for (const name of ['wdChooseMethod', 'wdConfirmHTML', 'wdQuote', 'depositTonkeeperStepHTML']) vm.runInContext(fn(name), c);
c.wdChooseMethod('stars');
assert.equal(c.step, 'amount');
assert.equal(c.wdState.coin.code, 'XTR');
assert.equal(c.wdState.coin.min, 50);
assert.equal(c.wdState.coin.decimals, 0);
c.wdQuote();
assert.match(c.error, /целое количество Stars/);
c.wdState.quote = {method: 'stars', username: '<attacker>', quantity: 50};
const confirmation = c.wdConfirmHTML();
assert.ok(confirmation.includes('@&lt;attacker>'));
assert.ok(!confirmation.includes('@<attacker>'));
assert.ok(!confirmation.includes('Чек придёт'));
assert.ok(confirmation.includes('Таймаут не означает отмену'));
const ton = c.depositTonkeeperStepHTML();
assert.ok(ton.includes('1.1 TON'));
assert.ok(ton.includes('&lt;wallet>'));
assert.ok(ton.includes('mainnet'));
assert.ok(!ton.includes('gram.png'));
assert.ok(!ton.includes('usdtDeeplink'));
assert.ok(source.includes('roundId: fairCheckUidInput.value.trim()'));
assert.ok(!source.includes('uid: fairCheckUidInput.value.trim()'));
assert.ok(source.includes('data.message || "Раунд найден. Полная проверка результата не выполнена."'));
assert.ok(source.includes('if (data.activeWithdrawal) { wdFinish(data.activeWithdrawal); return; }'));
console.log('Stars minimum/self-recipient confirmation, native TON escaping and fairness identity/result scope: passed');

vm.runInContext(fn('walletStatusHTML') + fn('walletAmountHTML'), c);
for (const status of ['queued', 'submitting', 'pending', 'blockchain_sent', 'uncertain', 'mismatch']) {
    assert.ok(c.walletStatusHTML({status}).includes('pending'), status);
    assert.ok(!c.walletStatusHTML({status}).includes('Успешно'), status);
    assert.ok(c.walletAmountHTML({status, amount: 50}, true).includes('waiting'), status);
}
