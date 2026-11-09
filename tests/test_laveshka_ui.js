const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app.js', 'utf8');
function fn(name) {
    const start = source.indexOf('function ' + name + '(');
    assert.ok(start >= 0);
    return source.slice(start, source.indexOf('\n}\n', start) + 3);
}
const escapeHtml = x => String(x).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const ctx = vm.createContext({depositState: {}, escapeHtml, fmtNum:String, depositPromoWaitingHTML:()=>'', depositTagWaitingHTML:()=>'', Date});
vm.runInContext(fn('depositLaveProvidersHTML') + fn('depositSbpTimerText') + fn('depositSbpWaitingHTML'),ctx);
ctx.depositState.laveProviders=[{id:7,name:'<script>',method:'phone',rate:'100',min_rub:'100',max_rub:'2000'}];
assert.match(ctx.depositLaveProvidersHTML(),/Пополнение телефона/);
assert.match(ctx.depositLaveProvidersHTML(),/&lt;script&gt;/);
ctx.depositState.sbpInvoice={state:'pending',method:'phone',payPhone:'+996123456789',payCountry:'KG',payOperator:'Test',rubAmount:'1000',rate:'100',amount:100,expiresIn:300};
let html=ctx.depositSbpWaitingHTML();
assert.match(html,/\+996123456789/);
assert.match(html,/Проверьте страну/);
assert.ok(!html.includes('data-deposit-open'));
ctx.depositState.sbpInvoice.expiresIn=0;
html=ctx.depositSbpWaitingHTML();
assert.ok(!html.includes('+996123456789'));
ctx.depositState.sbpInvoice.overdue=true;
assert.match(ctx.depositSbpWaitingHTML(),/Не платите/);
for (const name of ['depositCreateSbp','depositCreateLaveshka']) {
    assert.match(fn(name),/"Idempotency-Key": depositState.laveRequestKey/);
}
assert.match(fn('depositCreateSbp'),/providerId: depositState.laveProvider.id/);
assert.match(fn('depositLavePollFn'),/depositState.payUrl = data.payUrl/);
console.log('Laveshka UI tests passed');
