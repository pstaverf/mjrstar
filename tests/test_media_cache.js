const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('sw.js', 'utf8');
const origin = 'https://game.example';
const handlers = {};
const stores = new Map();
const deleted = [];
let network = 0, storageBlocked = false, writesBlocked = false;
let slowPutBarrier = null, slowPutStarted = null;
let networkReply = async () => new Response('asset', {headers: {'Content-Type': 'application/octet-stream'}});
function store(name) {
    if (!stores.has(name)) stores.set(name, new Map());
    const values = stores.get(name);
    return {
        match: async req => values.has(req.url) ? values.get(req.url).clone() : undefined,
        put: async (req, response) => {
            if (writesBlocked) throw new Error('quota');
            if (slowPutBarrier && req.url.endsWith('/slow.lottie')) {slowPutStarted(); await slowPutBarrier;}
            values.set(req.url, response.clone());
        },
        keys: async () => Array.from(values.keys(), url => new Request(url)),
        delete: async req => values.delete(req.url),
    };
}
const context = vm.createContext({
    URL, Request, Response, AbortController, setTimeout, clearTimeout, console,
    self: {location: {origin}, clients: {claim: async () => {}}, skipWaiting: async () => {}, addEventListener: (name, callback) => {handlers[name] = callback;}},
    caches: {
        open: async name => {if (storageBlocked) throw new Error('storage disabled'); return store(name);},
        keys: async () => Array.from(stores.keys()),
        delete: async name => {deleted.push(name); return stores.delete(name);},
    },
    fetch: async (req, options) => {network++; assert.ok(options.signal); return networkReply(req);},
});
vm.runInContext(source, context);
function intercepted(path, init) {
    let response;
    const req = new Request(new URL(path, origin), init);
    handlers.fetch({request: req, respondWith: value => {response = value;}});
    return response;
}
async function get(path, init) {
    const pending = intercepted(path, init);
    assert.ok(pending, 'expected intercepted public asset: ' + path);
    return await pending;
}
(async () => {
    // This fails with the old /\\./ regex: assets incorrectly used network-first.
    for (const path of ['/lottie/test.lottie', '/images/test.gif', '/images/test.webp', '/fonts/test.woff2', '/ИграКено/test.png']) {
        assert.equal(await (await get(path)).text(), 'asset');
        const before = network;
        assert.equal(await (await get(path)).text(), 'asset');
        assert.equal(network, before, path + ' must be cache-first');
    }
    const before = network;
    const bodies = await Promise.all(Array.from({length: 20}, async () => (await get('/lottie/shared.lottie')).text()));
    assert.deepEqual(bodies, Array(20).fill('asset'));
    assert.equal(network - before, 1, 'cold requests must coalesce and return independent bodies');
    for (const path of ['/api/balance', '/api/deposit/info', '/api/support/files/1.png', '/api/crash/state', '/api/ws-ticket', '/private/user.png', '/unknown.json', 'https://elsewhere.example/a.png']) {
        assert.equal(intercepted(path), undefined, path + ' must bypass all caching');
    }
    assert.equal(intercepted('/lottie/test.lottie', {method: 'POST'}), undefined);
    assert.equal(intercepted('/images/video.mp4', {headers: {Range: 'bytes=0-9'}}), undefined);
    const cdn = 'https://cdn.jsdelivr.net/npm/@lottiefiles/dotlottie-web@0.80.0/dist/';
    for (const file of ['index.js', 'dotlottie-player.wasm']) {
        await get(cdn + file);
        const count = network;
        await get(cdn + file);
        assert.equal(network, count, 'pinned runtime should be cached');
    }
    assert.equal(intercepted(cdn.replace('0.80.0', '0.79.0') + 'index.js'), undefined);
    // API auth / Telegram initData must never be persisted in static cache keys.
    await get('/images/key.png?v=2&initData=private-test-value', {headers: {'X-Telegram-Init-Data': 'private-test-value', Authorization: 'private-test-value'}});
    const media = stores.get('mjrstar-media-v1');
    assert.ok(media.has(origin + '/images/key.png?v=2'));
    assert.ok(!Array.from(media.keys()).some(key => key.includes('private-test-value')));
    const key = context.publicCacheKey(origin + '/images/key.png?initData=private-test-value');
    assert.equal(key.headers.has('Authorization'), false);
    assert.equal(key.headers.has('X-Telegram-Init-Data'), false);
    for (const [name, reply] of [
        ['placeholder', () => new Response('placeholder', {headers: {'X-MjrStar-Placeholder': '1'}})],
        ['html', () => new Response('<html>fallback</html>', {headers: {'Content-Type': 'text/html'}})],
        ['missing', () => new Response('missing', {status: 404})],
        ['private', () => new Response('private', {headers: {'Cache-Control': 'private, no-store'}})],
        ['large', () => new Response('large', {headers: {'Content-Length': String(7 * 1024 * 1024)}})],
    ]) {
        networkReply = async () => reply();
        const count = network;
        await get('/lottie/' + name + '.lottie');
        await get('/lottie/' + name + '.lottie');
        assert.equal(network - count, 2, name + ' response must not be cached');
    }
    networkReply = async () => new Response('ok');
    storageBlocked = true;
    assert.equal(await (await get('/lottie/no-storage.lottie')).text(), 'ok');
    storageBlocked = false;
    writesBlocked = true;
    assert.equal(await (await get('/lottie/no-quota.lottie')).text(), 'ok');
    writesBlocked = false;
    let releaseSlow, notifySlow;
    slowPutBarrier = new Promise(resolve => {releaseSlow = resolve;});
    const enteredSlow = new Promise(resolve => {notifySlow = resolve;});
    slowPutStarted = notifySlow;
    const slowAsset = get('/lottie/slow.lottie');
    await enteredSlow;
    let deadline;
    try {
        const fastAsset = await Promise.race([get('/lottie/other-game.lottie'), new Promise((resolve, reject) => {deadline = setTimeout(() => reject(new Error('slow asset blocked another game')), 1000);})]);
        assert.equal(await fastAsset.text(), 'ok');
    } finally {clearTimeout(deadline); releaseSlow();}
    await slowAsset;
    slowPutBarrier = null;
    for (let i = 0; i < 260; i++) await get('/images/bounded-' + i + '.png');
    assert.ok(media.size <= 256, 'persistent cache must remain bounded');
    networkReply = async () => {throw new Error('offline');};
    assert.equal(await (await get('/images/bounded-259.png')).text(), 'ok');
    assert.equal((await get('/images/not-in-cache.png')).status, 503);
    // Shell stays network-first, in a separate cache, with offline fallback.
    let shell = 0;
    networkReply = async () => new Response('shell-' + (++shell));
    assert.equal(await (await get('/app.js?v=build')).text(), 'shell-1');
    assert.equal(await (await get('/app.js?v=build')).text(), 'shell-2');
    networkReply = async () => {throw new Error('offline');};
    assert.equal(await (await get('/app.js?v=build')).text(), 'shell-2');
    stores.set('another-app-cache', new Map());
    stores.set('mjrstar-static-v32', new Map());
    stores.set('mjrstar-media-v0', new Map());
    let activated;
    handlers.activate({waitUntil: task => {activated = task;}});
    await activated;
    assert.ok(deleted.includes('mjrstar-static-v32'));
    assert.ok(deleted.includes('mjrstar-media-v0'));
    assert.ok(!deleted.includes('mjrstar-media-v1'));
    assert.ok(!deleted.includes('another-app-cache'));
    assert.ok(stores.has('mjrstar-static-v33'));
    console.log('Media cache: cache-first, coalescing, pinned runtime, private/API exclusions, offline/quota fallbacks, bounded storage and release cleanup: passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
