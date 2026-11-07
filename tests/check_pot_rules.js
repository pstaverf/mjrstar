const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("app.js", "utf8");
const start = source.indexOf("    const POT = (function() {");
const end = source.indexOf("    const PotDraw =", start);
const pot = vm.runInNewContext(source.slice(start, end) + "\nPOT;", {TextEncoder});
const geometryStart = source.indexOf("    function clipHalf(");
const geometryEnd = source.indexOf("    const avatarCache =", geometryStart);
const geometry = vm.createContext({WORLD: 1000});
vm.runInContext(source.slice(geometryStart, geometryEnd), geometry);
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
for (const item of cases) {
    assert.equal(pot.pickWinnerIndex(item.seed, item.id, item.cents.map(value => value / 100)), item.winner);
    const total = item.cents.reduce((a, b) => a + b, 0);
    for (let index = 0; index < item.cents.length; index++) {
        const polygon = geometry.powerCell(index, item.layout.seeds, item.layout.weights);
        let area = 0;
        for (let j = 0; j < polygon.length; j++) {
            const a = polygon[j], b = polygon[(j + 1) % polygon.length];
            area += a[0] * b[1] - b[0] * a[1];
        }
        area = Math.abs(area) / 2;
        assert.ok(Math.abs(area - item.cents[index] / total * 1000000) < 0.00001, "Territory area does not match the stake");
    }
}
assert.ok(source.includes('if (current) body.roundId = current;'));
assert.ok(source.includes('this.sim.tEnd / this.run.liveSec'));
