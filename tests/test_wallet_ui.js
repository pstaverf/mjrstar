const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("app.js", "utf8");
const html = fs.readFileSync("index.html", "utf8");
const brand = html.match(/<div class="rs-pl-brand"[^>]*>([\s\S]*?)<\/div>/)[1].replace(/<[^>]*>/g, "").trim();
assert.equal(brand, "MajorStars");

function topFunction(name) {
    const start = source.indexOf("function " + name + "(");
    assert.ok(start >= 0, name);
    return source.slice(start, source.indexOf("\n}\n", start) + 3);
}

const context = vm.createContext({
    depositState: {amount: 10, methodsEnabled: {cryptobot: true, xrocket: true, stars: true, tonkeeper: true}},
    DEPOSIT_METHOD_LABELS: Object.fromEntries(["cryptobot", "xrocket", "stars", "tonkeeper", "sbp", "laveshka"].map(key => [key, {icon: "", label: key}])),
    DEPOSIT_QUICK_AMOUNTS: [],
    depositPromoMethodInfo: () => null,
    depositTagMethodInfo: () => null,
    depositPromoBannerHTML: () => "",
    depositTagBannerHTML: () => "",
    depositPromoPreviewHTML: () => "",
    depositTagPreviewHTML: () => "",
    fmtNum: String,
    fmtCoef: String,
    lazyImgTag: () => "",
    liteAsset: value => value,
    psNum: value => String(value),
    profileStatRowHTML: (icon, label, value) => label + ":" + value,
    formatDate: String,
    escapeHtml: value => String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"),
    csRingAttr: () => "",
    checksBarRow: (label, cls, amount) => label + ":" + amount,
    PS_DAY_MILESTONES: [7, 30]
});
vm.runInContext(topFunction("depositMainStepHTML"), context);
const methods = context.depositMainStepHTML();
assert.ok(methods.indexOf('data-deposit-method="cryptobot"') < methods.indexOf('data-deposit-method="xrocket"'));
assert.ok(methods.indexOf('data-deposit-method="xrocket"') < methods.indexOf('data-deposit-method="stars"'));
assert.match(methods, /data-deposit-method="tonkeeper" disabled aria-disabled="true"/);
assert.match(methods, /временно недоступно/);
context.depositState.methodsEnabled.xrocket = false;
context.depositState.methodErrors = {xrocket: "xRocket: JWT повреждён <script>bad</script>"};
const unavailable = context.depositMainStepHTML();
assert.ok(!unavailable.includes('data-deposit-method="xrocket"'));
assert.match(unavailable, /JWT повреждён/);
assert.ok(unavailable.includes("&lt;script&gt;"));
assert.ok(!unavailable.includes("<script>"));
assert.ok(unavailable.includes('data-deposit-method="stars"'));
vm.runInContext(topFunction("profileStatsRowsHTML") + topFunction("profileStatsChartHTML"), context);
const stats = {balance: 1, turnover: 2, winPercent: 0, registrationDate: "2026-11-07", deposits: 0, cashouts: 0, bonuses: 12.5, daysWithUs: 1};
assert.match(context.profileStatsRowsHTML(stats), /Бонусы:12.5/);
assert.match(context.profileStatsChartHTML(stats), /Бонусы/);
assert.match(context.profileStatsChartHTML(stats), /data-to="12.5"/);
assert.match(context.profileStatsChartHTML(stats), /Бонусы:12.5/);

(async () => {
    const calls = [];
    let invoiceCallback;
    let polling;
    const paymentContext = vm.createContext({
        CURRENT_UID: 42,
        depositState: {amount: 10},
        fetch: async url => {
            calls.push(url);
            return {json: async () => url.endsWith("/create") ? {ok: true, invoiceId: "ms_order", invoiceLink: "https://t.me/$invoice", expiresIn: 1800} : {ok: true, paid: false}};
        },
        depositStartPolling: callback => polling = callback,
        renderDepositStep: () => {},
        tgWebApp: {openInvoice: (link, callback) => invoiceCallback = callback},
        depositStopPolling: () => {},
        loadUserState: () => {},
        showToast: () => {},
        haptic: () => {}
    });
    vm.runInContext(topFunction("depositCreateStars"), paymentContext);
    paymentContext.depositCreateStars();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(typeof polling, "function");
    assert.equal(paymentContext.depositState.invoiceId, "ms_order");
    invoiceCallback("paid");
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(paymentContext.depositState.step, "waiting");
    assert.ok(calls.includes("/api/deposit/stars/status?invoiceId=ms_order"));
    const elements = new Map();
    function element(id) {
        if (!elements.has(id)) elements.set(id, {dataset: {}, style: {}, handlers: {}, classList: {add() {}, remove() {}, toggle() {}}, querySelector: selector => selector === ".bonus-modal-card" ? element("card") : null, querySelectorAll: () => [], addEventListener(name, callback) { this.handlers[name] = callback; }});
        return elements.get(id);
    }
    const bonusState = {ok: true, existingBonus: {bioText: "@mjrstars", cooldownSeconds: 43200, queued: false, secondsLeft: 0, streak: 2, total: 4.5, baseMin: 1, baseMax: 3, streakBase: 0.1, streakStep: 0.05}};
    const bonusCalls = [];
    const bonusContext = vm.createContext({
        window: {},
        document: {getElementById: element},
        fetch: async url => {
            bonusCalls.push(url);
            return {json: async () => url.endsWith("/state") ? bonusState : {ok: true, state: {...bonusState, existingBonus: {...bonusState.existingBonus, queued: true, secondsLeft: 43200}}, balance: 1000, creditedAmount: 0, message: "Вы в очереди"}};
        },
        escapeHtml: String,
        lazyImgTag: () => "",
        liteAsset: value => value,
        setTimeout: () => 0,
        setInterval: () => 0,
        clearInterval: () => {},
        requestAnimationFrame: callback => callback(),
        CURRENT_UID: 42,
        applyBalance: () => {},
        loadProfileStats: () => {},
        haptic: () => {},
        showToast: text => { throw new Error(text); }
    });
    const bonusStart = source.indexOf('(function() {\n    const modal = document.getElementById("bonusModal")');
    const bonusEnd = source.indexOf("\n})();", bonusStart) + "\n})();".length;
    vm.runInContext(source.slice(bonusStart, bonusEnd), bonusContext);
    bonusContext.window.bonusRefreshBadge();
    await new Promise(resolve => setImmediate(resolve));
    element("bonusOpenBtn").handlers.click();
    assert.match(element("bonusContent").innerHTML, /Бонус за описание Telegram/);
    assert.match(element("bonusContent").innerHTML, /@mjrstars/);
    for (const action of ["goto-cashback", "goto-rakeback", "goto-table", "goto-giveaway", "goto-wheel"]) {
        assert.ok(element("bonusContent").innerHTML.includes(action), action + " must remain visible");
    }
    for (const action of ["goto-cashback", "goto-rakeback", "goto-table", "goto-giveaway"]) {
        const click = bn => element("bonusContent").handlers.click({target: {closest: selector => selector === "[data-bn]" ? {dataset: {bn}} : null}});
        click(action);
        assert.match(element("bonusContent").innerHTML, /Раздел сохранён/);
        assert.ok(!element("bonusContent").innerHTML.includes("NaN"));
        click("back");
        assert.match(element("bonusContent").innerHTML, /Бонус за описание Telegram/);
    }
    assert.equal(element("existingBonusClaim").disabled, false);
    element("bonusContent").handlers.click({target: {closest: selector => selector === "[data-bn]" ? {dataset: {bn: "claim-existing"}} : null}});
    await new Promise(resolve => setImmediate(resolve));
    assert.ok(bonusCalls.includes("/api/bonuses/existing/claim"));
    assert.equal(element("existingBonusClaim").disabled, true);
    assert.match(element("bonusAlertBody").innerHTML, /Вы в очереди/);
    console.log("MajorStars loading, deposit order, disabled Tonkeeper, bonus list/chart and existing-bonus UI, server-confirmed Stars: passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
