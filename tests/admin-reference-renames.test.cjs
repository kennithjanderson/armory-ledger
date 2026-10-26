const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {JSDOM} = require('jsdom');

const tick = () => new Promise(resolve => setImmediate(resolve));
const cases = [
    {
        resource: 'manufacturer',
        formId: 'manufacturer-name-update',
        script: 'app/static/js/admin-manufacturer-aliases.js',
        endpoint: '/admin/manufacturers/123/name',
        current: 'Smith & Wesson',
        next: 'Smith and Wesson',
        token: 'manufacturer-csrf',
    },
    {
        resource: 'caliber',
        formId: 'caliber-name-update',
        script: 'app/static/js/admin-caliber-aliases.js',
        endpoint: '/admin/calibers/456/name',
        current: '223',
        next: '.223',
        token: 'caliber-csrf',
    },
];

async function setup(item, {confirm = true, response = {ok: true, body: {success: true}}} = {}) {
    const dom = new JSDOM(`
        <form id="manufacturer-alias-create" data-endpoint="/aliases" data-csrf-token="alias-csrf">
            <input name="alias" value="S&amp;W">
        </form>
        <form id="caliber-alias-create" data-endpoint="/caliber-aliases" data-csrf-token="caliber-alias-csrf">
            <input name="alias" value="9x19">
        </form>
        <form id="${item.formId}" data-endpoint="${item.endpoint}"
              data-csrf-token="${item.token}" data-current-name="${item.current}">
            <input name="name" value="${item.next}">
        </form>
        <div id="manufacturer-alias-message"></div>
        <div id="caliber-alias-message"></div>
    `, {url: 'https://test.invalid/admin/references'});
    const requests = [];
    const confirmations = [];
    let reloads = 0;
    const window = {
        confirm(message) { confirmations.push(message); return confirm; },
        location: {reload() { reloads += 1; }},
    };
    const fetch = async (url, options) => {
        requests.push({url, options});
        return {ok: response.ok, json: async () => response.body};
    };
    vm.runInNewContext(fs.readFileSync(item.script, 'utf8'), {
        document: dom.window.document, window, fetch, JSON,
    });
    dom.window.document.dispatchEvent(new dom.window.Event('DOMContentLoaded'));
    const form = dom.window.document.getElementById(item.formId);
    form.dispatchEvent(new dom.window.Event('submit', {bubbles: true, cancelable: true}));
    await tick();
    return {dom, requests, confirmations, get reloads() { return reloads; }};
}

for (const item of cases) {
    test(`${item.resource} rename sends confirmed canonical name with CSRF and reloads`, async () => {
        const result = await setup(item);
        assert.equal(result.confirmations.length, 1);
        assert.match(result.confirmations[0], /shared change affects all users/);
        assert.match(result.confirmations[0], /old name remains an alias/);
        assert.equal(result.requests.length, 1);
        assert.equal(result.requests[0].url, item.endpoint);
        assert.equal(result.requests[0].options.method, 'PUT');
        assert.equal(result.requests[0].options.headers['X-CSRF-Token'], item.token);
        assert.deepEqual(JSON.parse(result.requests[0].options.body), {name: item.next});
        assert.equal(result.reloads, 1);
        result.dom.window.close();
    });

    test(`${item.resource} rename cancellation makes no request`, async () => {
        const result = await setup(item, {confirm: false});
        assert.equal(result.confirmations.length, 1);
        assert.equal(result.requests.length, 0);
        assert.equal(result.reloads, 0);
        result.dom.window.close();
    });
}
