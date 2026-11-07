const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("app.js", "utf8");
const start = source.indexOf("    const ESC = (function() {");
const end = source.indexOf("\n    const BASE =", start);
const engine = vm.runInNewContext(source.slice(start, end) + "\nESC;", {TextEncoder, Uint8Array, Uint32Array, Math});
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
for (const item of cases) {
    const outcome = engine.duelOutcome(item.seed, item.id, item.level.id, {...item.level, dlMin: 1.3, dlMax: 3, landPad: 0.08});
    for (const key of Object.keys(item.outcome)) {
        if (typeof item.outcome[key] === "number") assert.ok(Math.abs(outcome[key] - item.outcome[key]) < 1e-12, key);
        else assert.equal(outcome[key], item.outcome[key]);
    }
    outcome.slack = 0.6;
    outcome.slackLose = 0.3;
    const pathSeed = engine.hmacHex(item.seed, item.id + ":pvp:path");
    assert.equal(pathSeed, item.pathSeed);
    const duel = engine.generateDuel(pathSeed, item.level.gapDeg, outcome, outcome.creatorWins ? 0 : 1);
    assert.ok(duel, "Duel animation could not be generated");
    assert.equal(engine.validateDuel(duel, outcome).length, 0);
}
