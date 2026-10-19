const { test } = require("node:test");
const assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { JSDOM } = require("jsdom");

const root = path.join(__dirname, "..");
const markup = execFileSync(process.env.PYTHON || "python3", [
    path.join(__dirname, "render_ammunition_form.py"),
], { encoding: "utf8" });
const script = readFileSync(path.join(root, "app/static/js/ammunition-form.js"), "utf8");
const flush = () => new Promise(resolve => setImmediate(resolve));

async function setup(t, fetchResponse) {
    const dom = new JSDOM(markup, { url: "https://example.test/ammunition/new" });
    t.after(() => dom.window.close());
    const document = dom.window.document;
    document.getElementById("brand-name").value = "Example Maker";
    document.getElementById("caliber").innerHTML = '<option value="caliber-1">9mm</option>';
    document.getElementById("caliber").value = "caliber-1";
    document.getElementById("grain-weight").value = "115";
    document.getElementById("projectile-type").value = "FMJ";
    document.getElementById("quantity").value = "25";
    document.getElementById("acquired-date").value = "2026-10-19";
    const calls = [];
    const location = { href: "" };
    vm.runInNewContext(script, {
        document,
        window: { location },
        sessionStorage: dom.window.sessionStorage,
        fetch: async (url, options) => {
            calls.push({ url, options });
            return fetchResponse(JSON.parse(options.body));
        },
        console,
    });
    document.dispatchEvent(new dom.window.Event("DOMContentLoaded"));
    document.getElementById("ammunition-form").dispatchEvent(
        new dom.window.Event("submit", { cancelable: true }),
    );
    await flush();
    return { dom, document, calls, location };
}

const suggestions = () => ({ ok: true, json: async () => ({
    success: false,
    duplicate_suggestions: [{
        id: "owned-lot", brand: "Example Maker", caliber: "9mm",
        grain_weight: "115.00", projectile_type: "FMJ", quantity_on_hand: 40,
        created_at: "2026-10-01T12:00:00+00:00",
    }],
}) });

test("cancel closes suggestions and preserves form values without mutation", async t => {
    const { document, calls } = await setup(t, suggestions);
    assert.equal(calls.length, 1);
    assert.equal(document.getElementById("duplicate-ammunition-modal").hidden, false);
    assert.match(document.getElementById("duplicate-ammunition-list").textContent, /On hand: 40 rounds.*Requested: 25 rounds/);
    document.getElementById("duplicate-modal-cancel").click();
    assert.equal(document.getElementById("duplicate-ammunition-modal").hidden, true);
    assert.equal(document.getElementById("brand-name").value, "Example Maker");
    assert.equal(document.getElementById("quantity").value, "25");
    assert.equal(calls.length, 1);
});

test("create new explicitly resubmits and existing-lot handoff keeps quantity out of URL", async t => {
    let mode = "suggest";
    const context = await setup(t, async (payload) => {
        if (payload.create_separate_lot) {
            mode = "created";
            return { ok: true, json: async () => ({ success: true, lot: { id: "new-lot" } }) };
        }
        return suggestions();
    });
    context.document.getElementById("duplicate-create-new").click();
    await flush();
    assert.equal(mode, "created");
    assert.equal(JSON.parse(context.calls[1].options.body).create_separate_lot, true);
    assert.equal(context.location.href, "/ammunition/");

    const second = await setup(t, suggestions);
    second.document.querySelector("button[data-lot-id='owned-lot']").click();
    const handoff = JSON.parse(second.dom.window.sessionStorage.getItem("armoryAmmoActivityPrefill"));
    assert.equal(handoff.lotId, "owned-lot");
    assert.equal(handoff.quantity, 25);
    assert.equal(handoff.transactionType, "acquired");
    assert.match(second.location.href, /\/ammunition\/owned-lot\/activity\/new$/);
    assert.doesNotMatch(second.location.href, /25|quantity/i);
});

test("suggestion labels use text nodes rather than interpreting server text as HTML", async t => {
    const { document } = await setup(t, async () => ({ ok: true, json: async () => ({
        duplicate_suggestions: [{ id: "owned-lot", brand: "<img src=x>", caliber: "9mm",
            quantity_on_hand: 0, created_at: "2026-10-01" }],
    }) }));
    assert.equal(document.querySelector("#duplicate-ammunition-list img"), null);
    assert.match(document.querySelector("#duplicate-ammunition-list").textContent, /<img src=x>/);
});

test("activity page consumes only an unexpired matching lot prefill", async t => {
    const dom = new JSDOM(`
      <form id="ammunition-activity-form" data-lot-id="owned-lot">
        <select id="transaction_type"><option value="acquired">Acquired</option></select>
        <input id="quantity"><input id="occurred_date"><textarea id="notes"></textarea>
        <button id="ammunition-activity-save"></button><p id="ammunition-activity-error"></p>
      </form>`, { url: "https://example.test/ammunition/owned-lot/activity/new" });
    t.after(() => dom.window.close());
    const { document, sessionStorage } = dom.window;
    sessionStorage.setItem("armoryAmmoActivityPrefill", JSON.stringify({
        lotId: "owned-lot", quantity: 25, transactionType: "acquired", expiresAt: Date.now() + 10000,
    }));
    vm.runInNewContext(readFileSync(path.join(root, "app/static/js/ammunition-activity.js"), "utf8"), {
        document, window: { location: { href: "" } }, sessionStorage, fetch: async () => ({}), console,
    });
    document.dispatchEvent(new dom.window.Event("DOMContentLoaded"));
    assert.equal(document.getElementById("transaction_type").value, "acquired");
    assert.equal(document.getElementById("quantity").value, "25");
    assert.equal(sessionStorage.getItem("armoryAmmoActivityPrefill"), null);
});
