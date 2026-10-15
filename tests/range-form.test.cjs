const assert = require("node:assert/strict");
const { test } = require("node:test");
const { readFileSync } = require("node:fs");
const { execFileSync } = require("node:child_process");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const root = path.resolve(__dirname, "..");
const markup = execFileSync(process.env.PYTHON || "python3", [
    path.join(__dirname, "render_range_form.py"),
], { encoding: "utf8" });
const script = readFileSync(path.join(root, "app/static/js/range-form.js"), "utf8");

async function setup(t, initial = null) {
    const dom = new JSDOM(markup, { runScripts: "outside-only", url: "https://example.test/range/new" });
    t.after(() => dom.window.close());
    dom.window.rangeInitialData = initial;
    const loaded = new Promise(resolve => dom.window.document.addEventListener("DOMContentLoaded", resolve));
    dom.window.eval(script);
    await loaded;
    const document = dom.window.document;
    const change = (element, value, event = "change") => {
        element.value = value;
        element.dispatchEvent(new dom.window.Event(event, { bubbles: true }));
    };
    return { window: dom.window, document, change,
        card: () => document.querySelector(".range-firearm-card") };
}
const rows = card => [...card.querySelectorAll(".range-ammo-row")];
const lotSelect = row => row.querySelector(".range-ammo-lot");
const options = row => [...lotSelect(row).options].map(o => o.value).filter(Boolean);
const firearmSelect = card => card.querySelector(".range-firearm-select");

test("exact caliber options, labels, selection preservation and clearing", async t => {
    const { card, change } = await setup(t);
    const row = rows(card())[0];
    assert.deepEqual(options(row), []);
    change(firearmSelect(card()), "canik");
    assert.deepEqual(options(row), ["lot9"]);
    assert.match(lotSelect(row).options[1].textContent, /Batch <A>/);
    change(lotSelect(row), "lot9");
    change(firearmSelect(card()), "second9");
    assert.equal(lotSelect(row).value, "lot9");
    change(firearmSelect(card()), "rifle");
    assert.deepEqual(options(row), ["lot556"]);
    assert.equal(lotSelect(row).value, "");
});

test("independent cards and multiple rows, including removal", async t => {
    const { document, card, change } = await setup(t);
    const first = card();
    change(firearmSelect(first), "canik");
    first.querySelector(".range-add-ammo").click();
    rows(first).forEach(row => {
        assert.deepEqual(options(row), ["lot9"]);
        change(lotSelect(row), "lot9");
    });
    document.querySelector("#add-firearm").click();
    const second = document.querySelectorAll(".range-firearm-card")[1];
    change(firearmSelect(second), "rifle");
    assert.deepEqual(options(rows(second)[0]), ["lot556"]);
    change(firearmSelect(first), "empty");
    rows(first).forEach(row => assert.deepEqual(options(row), []));
    assert.deepEqual(options(rows(second)[0]), ["lot556"]);
    first.querySelector(".range-remove-ammo").click();
    first.querySelector(".range-remove-firearm").click();
    assert.deepEqual(options(rows(second)[0]), ["lot556"]);
});

test("missing caliber/no stock messages and Other / Borrowed submission", async t => {
    const { window, document, card, change } = await setup(t);
    const row = rows(card())[0];
    for (const [firearm, message] of [["unknown", /no recorded caliber/], ["empty", /No matching/]]) {
        change(firearmSelect(card()), firearm);
        assert.deepEqual(options(row), []);
        assert.match(row.querySelector(".range-ammo-hint").textContent, message);
    }
    change(row.querySelector(".range-ammo-source"), "other");
    change(row.querySelector(".range-ammo-quantity"), "15", "input");
    change(row.querySelector(".range-ammo-description"), "Borrowed", "input");
    assert.equal(document.querySelector("#range-save").disabled, false);
    assert.equal(lotSelect(row).disabled, true);
    assert.equal(row.querySelector(".range-ammo-quantity").hasAttribute("max"), false);
    let payload;
    window.fetch = async (url, request) => {
        payload = JSON.parse(request.body);
        return { ok: true, json: async () => ({ success: false, error: "Test response" }) };
    };
    document.querySelector("#range-form").dispatchEvent(new window.Event("submit", { cancelable: true }));
    assert.equal(payload.firearms[0].ammo_usage[0].ammo_lot_id, null);
    assert.equal(payload.firearms[0].ammo_usage[0].description, "Borrowed");
});

test("manipulated stale selection cannot submit", async t => {
    const { window, document, card, change } = await setup(t);
    change(firearmSelect(card()), "canik");
    const row = rows(card())[0];
    change(row.querySelector(".range-ammo-quantity"), "10", "input");
    const injected = window.document.createElement("option");
    injected.value = "lot556";
    injected.dataset.caliberId = "556";
    injected.dataset.onHand = "100";
    lotSelect(row).append(injected);
    change(lotSelect(row), "lot556");
    let called = false;
    window.fetch = () => { called = true; };
    document.querySelector("#range-form").dispatchEvent(new window.Event("submit", { cancelable: true }));
    assert.equal(called, false);
    assert.equal(document.querySelector("#range-save").disabled, true);
});

function history(lot, quantity = 10) {
    return { occurred_date: "2026-10-01", firearms: [{
        range_session_firearm_id: "association", firearm_id: "canik", ammo_usage: [{
            range_session_ammo_usage_id: "usage", source_type: "inventory", ammo_lot_id: lot, quantity,
        }],
    }] };
}

test("unchanged historical mismatch survives, changing quantity clears it", async t => {
    const { document, card, change } = await setup(t, history("lot556"));
    const row = rows(card())[0];
    assert.equal(lotSelect(row).value, "lot556");
    assert.match(row.querySelector(".range-ammo-hint").textContent, /Historical entry/);
    assert.equal(document.querySelector("#range-save").disabled, false);
    change(row.querySelector(".range-ammo-quantity"), "11", "input");
    assert.equal(lotSelect(row).value, "");
    assert.deepEqual(options(row), ["lot9"]);
    assert.equal(document.querySelector("#range-save").disabled, true);
});

test("historical zero-balance lot has original quantity available only on its row", async t => {
    const { card, change } = await setup(t, history("spent9"));
    const original = rows(card())[0];
    assert.equal(lotSelect(original).value, "spent9");
    assert.equal(original.querySelector(".range-ammo-quantity").max, "10");
    card().querySelector(".range-add-ammo").click();
    assert.deepEqual(options(rows(card())[1]), ["lot9"]);
    change(firearmSelect(card()), "rifle");
    assert.equal(lotSelect(original).value, "");
    assert.deepEqual(options(original), ["lot556"]);
});

test("activity dropdown defaults, preserves entries, and submits every type", async t => {
    const { window, document, card, change } = await setup(t);
    const activity = document.querySelector("#activity-type");
    assert.equal(activity.value, "range");
    assert.deepEqual([...activity.options].map(o => o.value), ["range", "hunting", "training", "defensive", "other"]);
    change(firearmSelect(card()), "canik");
    const row = rows(card())[0];
    change(lotSelect(row), "lot9");
    change(row.querySelector(".range-ammo-quantity"), "10", "input");
    let payload;
    window.fetch = async (url, request) => {
        assert.equal(url, "/range/");
        payload = JSON.parse(request.body);
        return { ok: true, json: async () => ({ success: false }) };
    };
    for (const value of ["range", "hunting", "training", "defensive", "other"]) {
        change(activity, value);
        assert.equal(lotSelect(row).value, "lot9");
        assert.equal(row.querySelector(".range-ammo-quantity").value, "10");
        document.querySelector("#range-form").dispatchEvent(new window.Event("submit", { cancelable: true }));
        assert.equal(payload.activity_type, value);
        assert.equal(payload.firearms[0].firearm_id, "canik");
        await new Promise(resolve => setImmediate(resolve));
    }
});

test("editing restores the recorded activity type", async t => {
    const initial = history("lot9");
    initial.activity_type = "defensive";
    const { document } = await setup(t, initial);
    assert.equal(document.querySelector("#activity-type").value, "defensive");
});

test("merged historical usage is preserved and locked, new rows exclude it", async t => {
    const { document, card } = await setup(t, history("merged9"));
    const row = rows(card())[0];
    assert.equal(lotSelect(row).value, "merged9");
    for (const selector of [".range-ammo-source", ".range-ammo-lot", ".range-ammo-quantity", ".range-remove-ammo"]) {
        assert.equal(row.querySelector(selector).disabled, true);
    }
    assert.equal(firearmSelect(card()).disabled, true);
    assert.equal(card().querySelector(".range-remove-firearm").disabled, true);
    assert.equal(document.querySelector("#range-save").disabled, false);
    assert.match(row.querySelector(".range-ammo-hint").textContent, /Merged lot/);
    card().querySelector(".range-add-ammo").click();
    assert.deepEqual(options(rows(card())[1]), ["lot9"]);
});
