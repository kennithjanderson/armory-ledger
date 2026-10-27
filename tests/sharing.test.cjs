const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');

const source = fs.readFileSync('app/static/js/sharing.js', 'utf8');
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

test('invitation submits email and independent section permissions with CSRF', async () => {
    const dom = new JSDOM(`
        <form id="share-invite-form" data-endpoint="/api/shares" data-csrf-token="invite-token">
            <input name="email" value="friend@example.test">
            <select name="firearms"><option value="ro" selected>RO</option></select>
            <select name="ammunition"><option value="rw" selected>RW</option></select>
            <select name="accessories"><option value="none" selected>None</option></select>
            <select name="shooting_log"><option value="rw" selected>RW</option></select>
            <button>Send</button>
        </form><span id="share-invite-result" role="status"></span>`,
        {runScripts: 'outside-only', url: 'https://ledger.example.test/sharing'});
    const calls = [];
    dom.window.fetch = async (url, options) => {
        calls.push({url, options});
        return {ok: true, json: async () => ({message: 'If this address can receive an invitation, one has been queued.'})};
    };
    dom.window.setTimeout = () => 1;
    dom.window.eval(source);
    dom.window.document.getElementById('share-invite-form').dispatchEvent(
        new dom.window.Event('submit', {bubbles: true, cancelable: true}));
    await tick();
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, '/api/shares');
    assert.equal(calls[0].options.method, 'POST');
    assert.equal(calls[0].options.headers['X-CSRF-Token'], 'invite-token');
    assert.deepEqual(JSON.parse(calls[0].options.body), {
        email: 'friend@example.test', firearms: 'ro', ammunition: 'rw', accessories: 'none', shooting_log: 'rw',
    });
    assert.match(dom.window.document.getElementById('share-invite-result').textContent, /one has been queued/);
    dom.window.close();
});

test('access updates and recipient acceptance call separate CSRF-protected routes', async () => {
    const dom = new JSDOM(`
        <form class="sharing-permission-form" data-share-id="share-1" data-csrf-token="edit-token">
            <select name="firearms"><option value="rw" selected>RW</option></select>
            <select name="ammunition"><option value="none" selected>None</option></select>
            <select name="accessories"><option value="none" selected>None</option></select>
            <select name="shooting_log"><option value="ro" selected>RO</option></select>
            <button>Save access</button><span role="status"></span>
        </form>
        <article class="sharing-entry"><button class="sharing-response" data-action="accept" data-share-id="share-2" data-csrf-token="accept-token">Accept</button><span role="status"></span></article>`,
        {runScripts: 'outside-only', url: 'https://ledger.example.test/sharing'});
    const calls = [];
    dom.window.fetch = async (url, options) => {
        calls.push({url, options});
        return {ok: true, json: async () => ({status: 'accepted'})};
    };
    dom.window.setTimeout = () => 1;
    dom.window.eval(source);
    dom.window.document.querySelector('.sharing-permission-form').dispatchEvent(
        new dom.window.Event('submit', {bubbles: true, cancelable: true}));
    dom.window.document.querySelector('.sharing-response').click();
    await tick();
    assert.equal(calls.length, 2);
    assert.equal(calls[0].url, '/api/shares/share-1/permissions');
    assert.equal(calls[0].options.method, 'PUT');
    assert.equal(calls[0].options.headers['X-CSRF-Token'], 'edit-token');
    assert.equal(calls[1].url, '/api/sharing-invitations/share-2/accept');
    assert.equal(calls[1].options.method, 'POST');
    assert.equal(calls[1].options.headers['X-CSRF-Token'], 'accept-token');
    dom.window.close();
});

test('sharing page explains acceptance and keeps each access section explicit', () => {
    const template = fs.readFileSync('app/templates/sharing.html', 'utf8');
    for (const section of ['firearms', 'ammunition', 'accessories', 'shooting_log']) {
        assert.match(template, new RegExp(`name="\\{\\{ section \\}\\}"`));
        assert.ok(template.includes(`'${section}'`));
    }
    assert.match(template, /recipient accepts/);
    assert.match(template, /email contains no inventory records/);
    assert.match(fs.readFileSync('app/templates/settings.html', 'utf8'), /href="\/sharing"/);
});
