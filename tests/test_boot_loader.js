const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('index.html', 'utf8');
const source = fs.readFileSync('app.js', 'utf8');
const helpers = html.slice(html.indexOf('            function resourceError('), html.indexOf('            function loadCssWithRetry('));
async function bootTest(response) {
    const timers = new Set();
    const context = vm.createContext({
        window: {AbortController}, AbortController,
        FETCH_TIMEOUT_MS: 30000,
        setTimeout(fn) {timers.add(fn); return fn;},
        clearTimeout(fn) {timers.delete(fn);},
        fetch: async (url, options) => {
            assert.equal(url, '/app_shell.html?v=test');
            assert.equal(options.cache, 'no-cache');
            return response;
        }
    });
    vm.runInContext(helpers, context);
    const promise = context.fetchTextWithRetry('/app_shell.html?v=test', 1, 0);
    return {promise, timers};
}
(async () => {
    let test = await bootTest({ok: false, status: 404});
    await assert.rejects(test.promise, e => e.resource === '/app_shell.html' && e.reason === 'HTTP 404');
    assert.equal(test.timers.size, 0);
    test = await bootTest({ok: true, headers: new Headers({'content-type': 'text/html'}), text: async () => '<html>proxy fallback</html>'});
    await assert.rejects(test.promise, /вместо оболочки/);
    assert.equal(test.timers.size, 0);
    let finishBody;
    test = await bootTest({ok: true, headers: new Headers({'content-type': 'text/html'}), text: () => new Promise(resolve => {finishBody = resolve;})});
    assert.equal(test.timers.size, 1, 'body transfer must still be timed');
    finishBody('<div id="arenaHubOpenBtn"></div><div id="balanceModalAmount"></div>');
    await test.promise;
    assert.equal(test.timers.size, 0);
    assert.ok(html.includes("fetchTextWithRetry('/app_shell.html?v='"));
    assert.ok(html.includes("loadCssWithRetry('/styles.css?v='"));
    assert.ok(html.includes("appScript.src = '/app.js?v='"));
    assert.ok(source.includes('navigator.serviceWorker.register("/sw.js")'));

    const loadState = source.slice(source.indexOf('function loadUserState() {'), source.indexOf('function loadReferralBase()'));
    for (const status of [401, 403, 404, 500]) {
        const elements = new Map();
        const scheduled = [];
        const context = vm.createContext({
            CURRENT_UID: 42, AbortController, console: {warn() {}},
            setTimeout(fn, ms) {scheduled.push(ms); return ms;}, clearTimeout() {},
            fetch: async () => ({ok: false, status}),
            document: {
                getElementById: id => elements.get(id),
                createElement: () => ({setAttribute() {}}),
                body: {appendChild(node) {elements.set(node.id, node);}}
            }
        });
        vm.runInContext(loadState, context);
        context.loadUserState();
        await new Promise(resolve => setImmediate(resolve));
        assert.ok(elements.get('profile-load-error').textContent.includes('HTTP ' + status));
        assert.equal(scheduled.includes(4000), status === 500);
    }
    console.log('Boot loader: root paths, resource diagnostics, HTTP fallback rejection, body timeout and profile failure feedback passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
