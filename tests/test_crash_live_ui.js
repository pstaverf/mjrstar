const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app.js', 'utf8');
function topFunction(name) {
    const start = source.indexOf('function ' + name + '(');
    assert.ok(start >= 0, name);
    return source.slice(start, source.indexOf('\n}\n', start) + 3);
}
let network = 0;
const toasts = [];
const button = {textContent: '', disabled: false, classList: {toggle() {}}};
const context = vm.createContext({
    crashBusy: false,
    betsAccepted: true,
    crashState: null,
    CRASH_FREEZE_SECONDS: 1,
    crashCountdownSeconds: state => state.remaining,
    fmtMult: String,
    fmtNum: String,
    crashLiveMult: () => 2,
    showToast: text => toasts.push(text),
    fetch: () => { network++; throw new Error('Must not POST a late bet'); },
    document: {getElementById: () => button},
});
for (const name of ['crashControlsFrozen', 'crashBetBtnState', 'crashDoBet', 'updateCrashBetBtn']) {
    vm.runInContext(topFunction(name), context);
}
assert.equal(context.crashBetBtnState(null).mode, 'off');
assert.equal(context.crashBetBtnState({status: 'waiting', remaining: 5}).mode, 'bet');
assert.equal(context.crashControlsFrozen({status: 'waiting', remaining: 1}), true);
for (const status of ['flying', 'crashed', 'unknown']) {
    context.crashState = {status};
    assert.equal(context.crashControlsFrozen(context.crashState), true);
    assert.equal(context.crashBetBtnState(context.crashState).mode, 'off');
    context.updateCrashBetBtn();
    assert.equal(button.disabled, true);
    context.crashDoBet();
}
assert.equal(network, 0);
assert.equal(toasts.length, 3);
context.crashState = {status: 'flying', myBet: {cashedOut: false}};
assert.equal(context.crashBetBtnState(context.crashState).mode, 'cashout');
context.updateCrashBetBtn();
assert.equal(button.disabled, false);
context.crashState = {status: 'waiting', remaining: 5};
context.updateCrashBetBtn();
assert.equal(button.disabled, false);
assert.ok(!source.includes('Поставить можно и во время полёта — ставка попадёт в следующий раунд.'));
assert.ok(source.includes('if (!body.roundId) body.roundId = liveRounds.get(liveAction[1]);'));
console.log('Crash live UI: betting only before launch, late POST guard, button locks, cashout preserved and explicit round binding: passed');
