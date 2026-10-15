const { test } = require("node:test");
const assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { JSDOM } = require("jsdom");
const markup = execFileSync(process.env.PYTHON || "python3", [path.join(__dirname, "render_merge_form.py")], {encoding: "utf8"});
const script = readFileSync(path.join(__dirname, "../app/static/js/ammunition-merge.js"), "utf8");
const flush = () => new Promise(resolve => setImmediate(resolve));

async function setup(t, respond, navigate = () => {}) {
    const dom = new JSDOM(markup, {url: "https://example.test/ammunition/source/merge"});
    t.after(() => dom.window.close());
    await new Promise(resolve => dom.window.document.addEventListener("DOMContentLoaded", resolve));
    const d = dom.window.document;
    const calls = [];
    vm.runInNewContext(script, {document: d, URL, AbortController, setTimeout, clearTimeout,
        window: {location: {origin: "https://example.test", assign: navigate}},
        fetch: async (url, options) => { calls.push({url, options}); return respond(url, options); },
    });
    d.dispatchEvent(new dom.window.Event("DOMContentLoaded"));
    const select = d.querySelector("select");
    const choose = value => { select.value = value; select.dispatchEvent(new dom.window.Event("change")); };
    const review = () => d.querySelector("#merge-review").click();
    const submit = () => d.querySelector("form").dispatchEvent(new dom.window.Event("submit", {cancelable: true}));
    return {d, calls, choose, review, submit};
}
const success = () => ({ok: true, status: 200, json: async () => ({success: true,
    destination_id: "destination", merge_id: "merge", redirect_url: "/ammunition/destination?merged=merge"})});

test("review quantities, cancel, focus, selection changes and explicit 409", async t => {
    const {d, calls, choose, review, submit} = await setup(t, () => ({ok: false, status: 409,
        json: async () => ({detail: "Inventory changed. Reload and review again."})}));
    submit();
    assert.equal(calls.length, 0);
    review();
    assert.match(d.querySelector("#merge-error").textContent, /Select a compatible/);
    choose("destination");
    d.querySelector("select").selectedOptions[0].dataset.quantity = "170";
    review();
    assert.match(d.querySelector("#merge-preview").textContent, /move 200 rounds/);
    assert.match(d.querySelector("#merge-balance").textContent, /170 to 370 rounds/);
    assert.match(d.querySelector("#merge-confirmation").textContent, /0 rounds.*archived as Merged/s);
    assert.equal(d.activeElement.id, "merge-submit");
    assert.equal(d.querySelector("#merge-submit").textContent, "Proceed with Merger");
    assert.ok(!d.querySelector("select").selectedOptions[0].textContent.includes("destination"));
    d.querySelector("#merge-cancel").click();
    assert.equal(d.activeElement.id, "merge-review");
    assert.equal(calls.length, 0);
    submit();
    assert.equal(calls.length, 0);
    review();
    choose("second");
    submit();
    assert.equal(calls.length, 0);
    review();
    submit(); submit();
    await flush();
    assert.equal(calls.length, 1);
    assert.equal(calls[0].options.headers["X-CSRF-Token"], "test-token");
    assert.deepEqual(JSON.parse(calls[0].options.body), {
        destination_id: "second", expected_source: 200, expected_destination: 50, confirmed: true,
    });
    assert.match(d.querySelector("#merge-error").textContent, /Inventory changed/);
    assert.equal(d.querySelector("#merge-confirmation").hidden, true);
});

test("HTTP 200 success redirects once without uncertain warning", async t => {
    let resolve;
    const redirects = [];
    const {d, calls, choose, review, submit} = await setup(t,
        () => new Promise(done => { resolve = done; }), url => redirects.push(url));
    choose("destination"); review(); submit(); submit();
    assert.equal(calls.length, 1);
    assert.equal(d.querySelector("#merge-submit").disabled, true);
    resolve(success());
    await flush();
    assert.deepEqual(redirects, ["/ammunition/destination?merged=merge"]);
    assert.doesNotMatch(d.querySelector("#merge-error").textContent, /could not be verified|Unable to confirm/);
    submit();
    assert.equal(calls.length, 1);
});

test("navigation exception after confirmed success is not an uncertain merge", async t => {
    const {d, choose, review, submit} = await setup(t, success, () => { throw new Error("navigation blocked"); });
    choose("destination"); review(); submit(); await flush();
    assert.match(d.querySelector("#merge-error").textContent, /Merge completed/);
    assert.doesNotMatch(d.querySelector("#merge-error").textContent, /could not be verified/);
    assert.equal(d.querySelector("#merge-destination-link").getAttribute("href"), "/ammunition/destination?merged=merge");
});

for (const [name, response] of [
    ["network failure", () => { throw new TypeError("network failure"); }],
    ["timeout", () => { throw new DOMException("timeout", "AbortError"); }],
    ["malformed JSON", () => ({ok: true, status: 200, json: async () => { throw new SyntaxError("not JSON"); }})],
    ["incomplete success", () => ({ok: true, status: 200, json: async () => ({success: true})})],
    ["external redirect", () => ({ok: true, status: 200, json: async () => ({success: true, destination_id: "destination", merge_id: "merge", redirect_url: "https://evil.example/ammunition/destination?merged=merge"})})],
    ["server error", () => ({ok: false, status: 500, json: async () => ({detail: "server error"})})],
]) {
    test(`${name} offers record links and never retries`, async t => {
        let navigated = false;
        const {d, calls, choose, review, submit} = await setup(t, response, () => { navigated = true; });
        choose("destination"); review(); submit(); await flush();
        assert.equal(navigated, false);
        assert.match(d.querySelector("#merge-error").textContent, /could not be verified/);
        assert.equal(d.querySelector("#merge-check-records").hidden, false);
        assert.equal(d.querySelector("#merge-destination-link").getAttribute("href"), "/ammunition/destination");
        review(); submit(); await flush();
        assert.equal(calls.length, 1);
        assert.equal(d.querySelector("#merge-submit").disabled, true);
    });
}
