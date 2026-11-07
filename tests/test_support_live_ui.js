const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app.js', 'utf8');
const support = fs.readFileSync('support.js', 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
(async () => {
    const start = source.indexOf('function loadBetsAcceptance()');
    const end = source.indexOf('\nloadBetsAcceptance();', start);
    let reply;
    const ctx = vm.createContext({betsAccepted: false, refreshBetsLockUI() {}, fetch: async () => ({json: async () => reply})});
    vm.runInContext(source.slice(start, end), ctx);
    for (const [data, expected] of [[{ok: true, accepting: true}, true], [{ok: true, accepting: false}, false], [{ok: true, betsAccepted: true}, true], [{ok: true, accepted: false}, false], [{ok: true}, false]]) {
        reply = data; ctx.loadBetsAcceptance(); await tick();
        assert.equal(ctx.betsAccepted, expected);
    }
    assert.ok(!fs.readFileSync('app_shell.html', 'utf8').includes('id="dogHouseOpenBtn"'));
    assert.ok(source.includes('gameSwitchOff.add("doghouse")'));
    assert.ok(source.includes('l.href = "/support.css?v="'));
    assert.ok(source.includes('s.src = "/support.js?v="'));

    let capturedSocket;
    const applied = [], events = [], calls = [];
    class FakeSocket {
        constructor(url) { this.url = url; this.sent = []; capturedSocket = this; }
        send(message) { this.sent.push(JSON.parse(message)); }
        close() {}
    }
    const window = {WebSocket: FakeSocket, location: {href: 'https://example.test/app/'}, addEventListener() {}, dispatchEvent(event) {events.push(event);}};
    const live = vm.createContext({
        window, WebSocket: FakeSocket, URL, AbortController,
        tgWebApp: {initData: 'signed-private-auth-data'}, CURRENT_UID: 42, currentGame: null,
        userDataLoaded: true, currentUser: {balance: 0}, applyBalance: amount => {applied.push(amount); live.currentUser.balance = amount;},
        supportBadgePoll() {calls.push('badge');},
        document: {hidden: false, addEventListener() {}},
        setTimeout() {return 1;}, clearTimeout() {},
        CustomEvent: class {constructor(type, options) {this.type = type; this.detail = options.detail;}},
        fetch: async (url, options) => {calls.push(url); assert.equal(options.method, 'POST'); return {ok: true, json: async () => ({ok: true, ticket: 'one-use-ticket'})};}
    });
    vm.runInContext(source.slice(source.indexOf('// Read-only real-time channel.')), live);
    await tick();
    assert.equal(capturedSocket.url, 'wss://example.test/api/ws');
    assert.ok(!capturedSocket.url.includes('ticket'));
    capturedSocket.onopen();
    assert.deepEqual(capturedSocket.sent, [{ticket: 'one-use-ticket'}]);
    capturedSocket.onmessage({data: JSON.stringify({type: 'state', balance: 100, supportRevision: [0, 0], games: []})});
    capturedSocket.onmessage({data: JSON.stringify({type: 'state', balance: 110, supportRevision: [1, 2], games: [{game: 'crash', phase: 'flying'}]})});
    capturedSocket.onmessage({data: JSON.stringify({type: 'state', balance: 110, supportRevision: [1, 2], games: [{game: 'crash', phase: 'flying'}]})});
    assert.deepEqual(applied, [100, 110]);
    assert.equal(events.at(-2).detail.supportChanged, true);
    assert.equal(events.at(-2).detail.gamesChanged, true);
    assert.ok(calls.includes('badge'));

    assert.ok(support.includes("s.isAdmin ? 'Все обращения · администратор' : 'Мои обращения'"));
    assert.ok(support.includes('data-support-file='));
    assert.ok(!support.includes('<img loading="lazy" src="/api/support/file'));
    assert.ok(support.includes('fetch("/api/support/file?t="'));
    assert.ok(support.includes('if (S.view === "ticket") poll();'));
    const ownStart = support.indexOf('    function ownMessage(');
    const ownEnd = support.indexOf('    function copyText(', ownStart);
    const ownership = vm.createContext({CURRENT_UID: 99, S: {ticket: {status: 'open'}, ban: null, state: {limits: {editWindow: 172800}}}});
    vm.runInContext(support.slice(ownStart, ownEnd), ownership);
    assert.equal(ownership.ownMessage({userId: 99, author: 'staff'}), true);
    assert.equal(ownership.canEditMsg({userId: 99, author: 'staff', createdAt: Date.now() / 1000}), true);
    assert.equal(ownership.canEditMsg({userId: 42, author: 'user', createdAt: Date.now() / 1000}), false);
    // Deleted messages must advance the cursor without creating empty chat bubbles.
    const appendStart = support.indexOf('    function appendMessages(');
    const appendEnd = support.indexOf('    function scrollEnd(', appendStart);
    const deleted = vm.createContext({
        S: {msgs: [], lastId: 0},
        listEl: () => ({querySelector() {throw new Error('Deleted row rendered');}}),
        nearBottom: () => true,
        document: {getElementById: () => null}
    });
    vm.runInContext(support.slice(appendStart, appendEnd), deleted);
    deleted.appendMessages([{id: 7, deleted: true}], false);
    assert.equal(deleted.S.lastId, 7);
    assert.equal(deleted.S.msgs.length, 0);
    console.log('Bet acceptance contract, removed DogHouse, WebSocket auth and updates, support roles and protected images: passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
