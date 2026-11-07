const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const {webcrypto} = require("node:crypto");
const page = fs.readFileSync("doghouse.html", "utf8");
const start = page.indexOf("const hex=");
const end = page.indexOf("(async()=>{try{await refresh();", start);
const script = page.slice(start, end);
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
(async () => {
    for (const data of cases) {
        const elements = new Map();
        const byId = id => {
            if (!elements.has(id)) elements.set(id, {});
            return elements.get(id);
        };
        const context = vm.createContext({byId, last: data, TextEncoder, crypto: webcrypto});
        vm.runInContext(script, context);
        await byId("verify").onclick();
        assert.ok(byId("verifyResult").textContent.startsWith("✓"), byId("verifyResult").textContent);
        data.payoutCents += 1;
        await byId("verify").onclick();
        assert.ok(byId("verifyResult").textContent.startsWith("✗"));
    }
})().catch(error => {console.error(error); process.exitCode = 1;});
