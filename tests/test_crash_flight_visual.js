const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app.js', 'utf8');
function topFunction(name) {
    const start = source.indexOf('function ' + name + '(');
    assert.ok(start >= 0, name);
    return source.slice(start, source.indexOf('\n}\n', start) + 3);
}
let now = 1000000;
const nodes = {
    crashRocketImg: {style: {}},
    crashTrailPath: {setAttribute(name, value) {this[name] = value;}},
    crashFillPath: {setAttribute(name, value) {this[name] = value;}},
    crashFlightStage: {getBoundingClientRect: () => ({width: 330, height: 230})},
};
const context = vm.createContext({Date: {now: () => now}, document: {getElementById: id => nodes[id]}, crashSkinArtAngle: undefined});
vm.runInContext(source.slice(source.indexOf('const CRASH_PATH_START ='), source.indexOf('const CRASH_SVG_DEFS =')), context);
for (const name of ['crashLiveMult', 'crashProgress', 'crashPointAt', 'crashRocketPos', 'crashCurvePoints', 'crashPathsFromPoints', 'crashComputeRocketAngle', 'updateCrashFlightVisual']) vm.runInContext(topFunction(name), context);
const state = {status: 'flying', flyingStartedAt: now, growth: 0.1};
let lastLeft = -Infinity, lastTop = Infinity;
for (const mult of [1, 1.01, 1.1, 1.5, 2, 3, 10, 42]) {
    now = state.flyingStartedAt + Math.log(mult) / state.growth * 1000;
    context.updateCrashFlightVisual(state);
    const left = parseFloat(nodes.crashRocketImg.style.left);
    const top = parseFloat(nodes.crashRocketImg.style.top);
    assert.ok(left > lastLeft, 'rocket must move right even below x1.1, not remain clamped until x3');
    assert.ok(top < lastTop, 'rocket must rise immediately after launch');
    assert.ok(!nodes.crashRocketImg.style.transform.includes('NaN'), 'missing skin angle must retain default rotation');
    assert.ok(!nodes.crashTrailPath.d.includes('NaN'));
    assert.ok(nodes.crashTrailPath.d.endsWith(left.toFixed(2) + ' ' + top.toFixed(2)), 'trail endpoint must follow rocket');
    lastLeft = left; lastTop = top;
}
context.updateCrashFlightVisual({status: 'crashed', crashPoint: 2, growth: 0.1});
assert.ok(nodes.crashRocketImg.style.top);
assert.ok(nodes.crashFillPath.d.endsWith(' Z'));
const end = context.crashRocketPos(context.crashPointAt(2));
assert.equal(parseFloat(nodes.crashRocketImg.style.top), end.top);
assert.equal(parseFloat(nodes.crashRocketImg.style.left), end.left);
console.log('Crash visual: rocket and trail move immediately at low multipliers, finite skin rotation and exact final crash position: passed');
