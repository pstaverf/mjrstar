const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const {webcrypto} = require("node:crypto");
const source = fs.readFileSync("app.js", "utf8");
const start = source.indexOf("(function() {\n    const nativeFetch");
const end = source.indexOf("\n})();", start) + "\n})();".length;
const calls = [];
const window = {
    location: {href: "https://preview.example/app", origin: "https://preview.example"},
    Telegram: {WebApp: {initData: "signed-session"}},
    fetch: async (url, init) => {
        calls.push({url, init});
        const target = new URL(url, "https://preview.example");
        const game = target.pathname.split("/")[2];
        const room = Number(target.searchParams.get("room") || JSON.parse(init && init.body || "{}").room || 1);
        return new Response(JSON.stringify({ok: true, room: {id: room}, round: {id: game + room}}), {headers: {"Content-Type": "application/json"}});
    }
};
vm.runInNewContext(source.slice(start, end), {window, URL, Headers, crypto: webcrypto});
(async () => {
    for (const game of ["portal", "race", "bomb", "sumo"]) {
        await window.fetch("/api/" + game + "/state?room=1");
        await window.fetch("/api/" + game + "/state?room=2");
        for (const room of [1, 2]) {
            await window.fetch("/api/" + game + "/join", {method: "POST", body: JSON.stringify({room, bet: 10})});
            const call = calls.at(-1);
            assert.equal(JSON.parse(call.init.body).roundId, game + room);
            assert.equal(call.init.headers.get("X-Telegram-Init-Data"), "signed-session");
            assert.ok(call.init.headers.get("Idempotency-Key"));
        }
    }
    await window.fetch("https://other.example/api/race/join", {method: "POST", body: "{}"});
    assert.equal(calls.at(-1).init.headers, undefined);
    console.log("Pot room versions and same-origin authorization: passed");
})().catch(error => {console.error(error); process.exitCode = 1;});
