const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');

const source = fs.readFileSync('app/static/js/armory.js', 'utf8');
const tick = () => new Promise(resolve => setTimeout(resolve, 20));

test('administrator footer status loads on hover, supports click and closes on outside click', async () => {
    const dom = new JSDOM(`<span class="admin-status-popover">
        <button id="system-status" data-admin-status aria-expanded="false"><span class="app-footer-status-text">CHECKING</span></button>
        <span id="admin-status-tooltip" hidden><span id="admin-status-database"></span><span id="admin-status-backups"></span><span id="admin-status-email"></span></span>
    </span>`, {runScripts: 'outside-only', url: 'https://example.test', pretendToBeVisual: true});
    const calls = [];
    dom.window.fetch = async url => {
        calls.push(url);
        return url === '/health'
            ? {ok: true, json: async () => ({status: 'healthy'})}
            : {ok: true, json: async () => ({database: 'connected', backups: {status: 'healthy', storage: 'writable', encryption: 'ready', scheduler: 'disabled', recovery: 'clear'}, email: 'disabled'})};
    };
    dom.window.eval(source);
    await tick();
    const wrapper = dom.window.document.querySelector('.admin-status-popover');
    const trigger = dom.window.document.getElementById('system-status');
    const tooltip = dom.window.document.getElementById('admin-status-tooltip');
    wrapper.dispatchEvent(new dom.window.MouseEvent('mouseenter'));
    await tick();
    assert.equal(tooltip.hidden, false);
    assert.equal(dom.window.document.getElementById('admin-status-database').textContent, 'connected');
    assert.match(dom.window.document.getElementById('admin-status-backups').textContent, /encryption ready/);
    assert.equal(dom.window.document.getElementById('admin-status-email').textContent, 'disabled');
    assert.ok(calls.includes('/admin/operational-status'));
    wrapper.dispatchEvent(new dom.window.MouseEvent('mouseleave'));
    assert.equal(tooltip.hidden, true);
    trigger.click();
    assert.equal(trigger.getAttribute('aria-expanded'), 'true');
    dom.window.document.body.click();
    assert.equal(tooltip.hidden, true);
    assert.equal(trigger.getAttribute('aria-expanded'), 'false');
    dom.window.close();
});

test('non-admin footer does not request administrative operational details', async () => {
    const dom = new JSDOM('<span id="system-status"><span class="app-footer-status-text">CHECKING</span></span>', {runScripts: 'outside-only', url: 'https://example.test'});
    const calls = [];
    dom.window.fetch = async url => { calls.push(url); return {ok: true, json: async () => ({status: 'healthy'})}; };
    dom.window.eval(source);
    await tick();
    assert.ok(calls.includes('/health'));
    assert.ok(!calls.includes('/admin/operational-status'));
    dom.window.close();
});
