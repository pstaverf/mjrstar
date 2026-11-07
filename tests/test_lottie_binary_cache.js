const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app.js', 'utf8');
let code = source.slice(source.indexOf('const LOTTIE_BINARY_MAX_BYTES'), source.indexOf('const LOTTIE_DPR ='));
// Small budgets exercise the same eviction algorithm without large test buffers.
code = code.replace('8 * 1024 * 1024', '12').replace('LOTTIE_BINARY_MAX_ENTRIES = 128', 'LOTTIE_BINARY_MAX_ENTRIES = 3');
let calls = 0;
let reply = async () => new Response(new Uint8Array([1, 2, 3, 4]));
class NativePlayer { constructor(options) {this.options = options;} }
const context = vm.createContext({
    URL, AbortController, setTimeout, clearTimeout,
    window: {location: {href: 'https://game.example/app', origin: 'https://game.example'}},
    fetch: async (url, options) => {calls++; assert.equal(options.credentials, 'omit'); return reply(url);},
    loadDotLottie: async () => NativePlayer,
});
vm.runInContext(code, context);
(async () => {
    const src = '/lottie/game.lottie';
    const classes = await Promise.all(Array.from({length: 12}, () => context.loadCachedDotLottie(src)));
    assert.equal(calls, 1, 'concurrent players must share one byte fetch');
    const a = new classes[0]({src, canvas: 'canvas-a', loop: true});
    const b = new classes[1]({src, canvas: 'canvas-b', loop: false});
    assert.notEqual(a, b);
    assert.notEqual(a.options.data, b.options.data);
    assert.equal(a.options.canvas, 'canvas-a');
    assert.equal(b.options.canvas, 'canvas-b');
    assert.equal(a.options.src, undefined);
    new Uint8Array(a.options.data)[0] = 99;
    assert.equal(new Uint8Array(b.options.data)[0], 1);
    const Next = await context.loadCachedDotLottie(src);
    assert.equal(new Uint8Array(new Next({src}).options.data)[0], 1, 'decoder must not mutate shared cache');
    assert.equal(calls, 1);
    for (const url of ['/api/private.lottie', '/private/file.lottie', 'https://elsewhere.example/file.lottie', '/images/test.png']) {
        assert.equal(await context.loadCachedDotLottie(url), NativePlayer);
    }
    assert.equal(calls, 1, 'private/foreign/non-Lottie URLs must not enter shared byte loader');
    for (const kind of ['placeholder', 'html', 'empty', 'failed']) {
        reply = async () => {
            if (kind === 'placeholder') return new Response('not-an-animation', {headers: {'X-MjrStar-Placeholder': '1'}});
            if (kind === 'html') return new Response('<html>fallback</html>', {headers: {'Content-Type': 'text/html'}});
            if (kind === 'empty') return new Response('');
            return new Response('error', {status: 500});
        };
        const count = calls;
        assert.equal(await context.loadCachedDotLottie('/lottie/' + kind + '.lottie'), NativePlayer);
        assert.equal(await context.loadCachedDotLottie('/lottie/' + kind + '.lottie'), NativePlayer);
        assert.equal(calls - count, 2, kind + ' must not poison the cache');
    }
    reply = async () => new Response(new Uint8Array([1, 2, 3, 4]));
    for (const name of ['second', 'third']) await context.getLottieBinary('/lottie/' + name + '.lottie');
    await context.getLottieBinary(src); // refresh LRU position
    await context.getLottieBinary('/lottie/fourth.lottie');
    assert.equal(vm.runInContext('lottieBinaryCache.size', context), 3);
    assert.equal(vm.runInContext('lottieBinaryBytes', context), 12);
    const count = calls;
    await context.getLottieBinary('/lottie/second.lottie');
    assert.equal(calls, count + 1, 'least recently used bytes must be evicted');
    reply = async () => new Response(new Uint8Array(8));
    await context.getLottieBinary('/lottie/larger.lottie');
    assert.ok(vm.runInContext('lottieBinaryBytes <= LOTTIE_BINARY_MAX_BYTES', context));
    assert.ok(vm.runInContext('lottieBinaryCache.size <= LOTTIE_BINARY_MAX_ENTRIES', context));
    for (const needle of ['loadCachedDotLottie(CF_LOTTIE[side])', 'loadCachedDotLottie(v === 2 ? BALL2_LOTTIE_URL : BALL_LOTTIE_URL)', 'loadCachedDotLottie(LOTTIE_URL)']) assert.ok(source.includes(needle));
    assert.equal((source.match(/new DotLottie\(/g) || []).length, 6);
    assert.equal((source.match(/loadCachedDotLottie\([^\n]+\)\.then/g) || []).length, 6, 'every current player construction path must use the cache');
    console.log('Lottie byte cache: single-flight, per-player buffer ownership, all player paths, bad-response recovery and byte/count LRU budgets: passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
