const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("app.js", "utf8");
let calls = 0;
let quoteAllowed = true;
const badge = {};
const context = vm.createContext({
    LIVE_MULT: {},
    fmtCoef: String,
    document: {getElementById: () => badge},
    fetch: async () => {
        calls++;
        return {json: async () => quoteAllowed ? {ok: true, multiplier: 5.4, variable: false} : {ok: false, error: "quote unavailable"}};
    },
    round2: value => Math.round(value * 100) / 100
});
vm.runInContext(source.slice(source.indexOf("const emojiQuoteRequests ="), source.indexOf("function gamePlayFetch(")), context);
vm.runInContext(source.slice(source.indexOf("function emojiProofLinksHTML("), source.indexOf("function openEmojiRoundModal(")), context);
const start = source.indexOf("    function pvpMoneySplit(");
vm.runInContext(source.slice(start, source.indexOf("    function pvpUpdateStats(", start)), context);

(async () => {
    await Promise.all([context.loadEmojiQuote("dice", "Шесть"), context.loadEmojiQuote("dice", "Шесть")]);
    assert.equal(calls, 1);
    assert.equal(context.LIVE_MULT.dice["Шесть"], 5.4);
    assert.equal(badge.textContent, "x5.4");
    quoteAllowed = false;
    await assert.rejects(context.loadEmojiQuote("dice", "Один"), /quote unavailable/);
    quoteAllowed = true;
    await context.loadEmojiQuote("dice", "Один");
    assert.equal(calls, 3);
    const links = context.emojiProofLinksHTML({checkLinks: ["https://t.me/mjrstars/1", "https://t.me/mjrstars/2", "https://t.me/c/1234/3"]});
    assert.ok(links.includes("Бросок 2"));
    assert.ok(links.includes("Бросок 3"));
    assert.ok(!links.includes('href="https://t.me/mjrstars/1"'));
    assert.equal(context.emojiProofLinksHTML({checkLinks: ["https://t.me/mjrstars/1", 'javascript:alert(1)"']}), "");
    assert.equal(context.emojiProofLinksHTML({}), "");
    for (const bet of [0.1, 0.15, 1, 10, 1000]) {
        const result = context.pvpMoneySplit(bet, 1);
        const expected = Math.floor(Math.round(bet * 200) * 99 / 100) / 100;
        assert.equal(result.prize, expected);
        assert.equal(Math.round((result.fee + result.prize) * 100), Math.round(bet * 200));
    }
    for (const game of ["dice", "slots", "bowl", "darts", "basket", "foot"]) {
        assert.ok(source.includes('loadEmojiQuote("' + game + '", outcome).catch(() => {});'));
    }
    assert.ok(source.includes('return loadEmojiQuote(game, body.outcome).then(() => fetch(url,'));
    console.log("Emoji quotes, recovery, proof links and Escape PvP cents: passed");
})().catch(error => {console.error(error); process.exitCode = 1;});
