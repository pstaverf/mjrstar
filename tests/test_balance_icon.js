const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("app.js", "utf8");
const context = vm.createContext({});
vm.runInContext(source.slice(source.indexOf("function formatMoney("), source.indexOf("function isAllowedAmountKey(")), context);
for (const value of [0, 10, 10.25, 1000, 1000000.99]) {
    const html = context.balanceAmountHTML(value);
    assert.equal((html.match(/<img /g) || []).length, 1);
    assert.ok(html.includes('src="/images/TelegramStars.png"'));
    assert.ok(html.includes('class="balance-value"'));
    assert.ok(html.includes('width="26" height="26"'));
    assert.ok(html.includes('style="width:1.25em;height:1.25em;max-width:1.25em;max-height:1.25em;object-fit:contain;flex-shrink:0;margin-inline-start:.3em;margin-inline-end:0;vertical-align:-.2em"'));
    assert.ok(!html.includes("⭐"));
    assert.ok(html.indexOf('class="balance-value"') < html.indexOf('class="balance-currency"'));
}
assert.ok(context.balanceAmountHTML(10, true).includes(">000.00</span>"));
assert.equal(context.formatMoney(10.25), "⭐️ 10.25");
assert.equal(context.formatMoney(1000), "⭐️ 1.000");
let renders = 0;
let number = null;
const element = {
    querySelector(selector) {
        assert.equal(selector, ".balance-value");
        return number;
    },
    set innerHTML(value) {
        renders++;
        assert.ok(value.includes("TelegramStars.png"));
        number = {textContent: ""};
    }
};
context.setBalanceAmount(element, 10);
for (let value = 11; value <= 30; value++) context.setBalanceAmount(element, value);
assert.equal(renders, 1);
assert.equal(number.textContent, "30");
const shell = fs.readFileSync("app_shell.html", "utf8");
assert.equal((shell.match(/class="balance-currency"/g) || []).length, 4);
assert.ok(!/class="amount text-skel">⭐/.test(shell));
assert.ok(!source.includes("balanceModalAmount.textContent = formatMoney"));
assert.ok(!source.includes('bal.querySelector("b").textContent = formatMoney'));
assert.ok(fs.existsSync("images/TelegramStars.png"));

assert.equal((shell.match(/class="balance-currency" width="26" height="26"/g) || []).length, 4);

for (const match of shell.matchAll(/<img\b[^>]*class="balance-currency"[^>]*>/g)) {
    assert.ok(match[0].includes('style="width:1.25em;height:1.25em;max-width:1.25em;max-height:1.25em;object-fit:contain;flex-shrink:0;margin-inline-start:.3em;margin-inline-end:0;vertical-align:-.2em"'));
}
assert.ok(source.includes('src="images/TelegramStars.png" width="24" height="24" style="width:24px;height:24px;object-fit:contain"'));
const index = fs.readFileSync("index.html", "utf8");
assert.ok(index.includes("majorstars-media-flight-20261107-9"));
assert.ok(fs.readFileSync("sw.js", "utf8").includes("mjrstar-static-v33"));
console.log("Balance currency image, intrinsic and inline dimensions, loading state, animation and cache version: passed");
