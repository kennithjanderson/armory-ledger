const test = require('node:test');
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const fs = require('node:fs');
const vm = require('node:vm');
const {JSDOM} = require('jsdom');
const python = process.env.PYTHON || 'python3';
const script = fs.readFileSync('app/static/js/admin-announcements.js', 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
async function setup(existing = false, zone = 'America/Chicago', gate = null) {
    const html = execFileSync(python, ['tests/render_announcement_form.py', ...(existing ? ['existing'] : [])], {encoding:'utf8', env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});
    const dom = new JSDOM(html, {url:'https://test.invalid/admin/announcements/new', runScripts:'outside-only'});
    await new Promise(resolve => dom.window.document.addEventListener('DOMContentLoaded', resolve, {once:true}));
    dom.window.eval(fs.readFileSync("app/static/js/date-time.js", "utf8"));
    const requests = [], navigation = {};
    const fetch = async (url, options) => {
        const payload = JSON.parse(options.body); requests.push({url,payload,options});
        if (url.endsWith('schedule-preview')) {
            if (gate) await gate(payload);
            const result = JSON.parse(execFileSync(python, ['tests/render_announcement_form.py','preview', JSON.stringify(payload)], {encoding:'utf8',env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}}));
            return {ok:result.ok, json:async()=>result.data};
        }
        return {ok:true,json:async()=>({success:true})};
    };
    vm.runInNewContext(script, {document:dom.window.document, window:{location:navigation, ArmoryDateTime:dom.window.ArmoryDateTime},
        Option:dom.window.Option, Intl:{DateTimeFormat:()=>({resolvedOptions:()=>({timeZone:zone})})}, fetch});
    dom.window.document.dispatchEvent(new dom.window.Event('DOMContentLoaded'));
    await tick();
    const get = id => dom.window.document.getElementById(id);
    const change = async (id,value,event='input') => {get(id).value=value;get(id).dispatchEvent(new dom.window.Event(event));await tick();};
    return {dom,get,change,requests,navigation};
}

test('browser default, winter/summer UTC previews and timezone change preserving instant', async()=>{
    const f = await setup();
    assert.equal(f.get('schedule-zone').value,'America/Chicago');
    await f.change('starts-at','2026-01-15T09:00');
    assert.match(f.get('starts-preview').textContent,/15:00 UTC/);
    await f.change('starts-at','2026-07-15T09:00');
    assert.match(f.get('starts-preview').textContent,/14:00 UTC/);
    await f.change('schedule-zone','UTC','change');
    assert.match(f.get('starts-at').value,/14:00/);
    assert.match(f.get('starts-preview').textContent,/14:00 UTC/);
    f.dom.window.close();
});

test('timezone change during initial load ignores stale responses and preserves stored instant', async()=>{
    const waiting=[];
    let calls=0;
    const f=await setup(true,'America/Chicago',()=> ++calls <= 2
        ? new Promise(resolve=>waiting.push(resolve)) : Promise.resolve());
    await f.change('schedule-zone','UTC','change');
    assert.match(f.get('starts-at').value,/07:30:12/);
    waiting.forEach(resolve=>resolve());await tick();
    assert.match(f.get('starts-at').value,/07:30:12/);
    assert.match(f.get('starts-preview').textContent,/07:30 UTC/);
    f.dom.window.close();
});

test('other browser timezone and missing browser timezone fallback', async()=>{
    for (const zone of ['Asia/Kolkata','']) {
        const f=await setup(false,zone);
        assert.equal(f.get('schedule-zone').value,zone||'UTC');
        await f.change('starts-at','2026-07-15T09:00');
        assert.match(f.get('starts-preview').textContent,zone?/03:30 UTC/:/09:00 UTC/);
        f.dom.window.close();
    }
});

test('gap rejected, fold requires occurrence, invalid zone errors', async()=>{
    const f=await setup();
    await f.change('starts-at','2026-03-08T02:30');
    assert.match(f.get('starts-preview').textContent,/does not exist/);
    await f.change('starts-at','2026-11-01T01:30');
    assert.match(f.get('starts-preview').textContent,/occurs twice/);
    assert.equal(f.get('starts-occurrence').value,'');
    await f.change('starts-occurrence','later','change');
    assert.match(f.get('starts-preview').textContent,/07:30 UTC/);
    await f.change('starts-occurrence','earlier','change');
    assert.match(f.get('starts-preview').textContent,/06:30 UTC/);
    await f.change('schedule-zone','Not/Valid','change');
    assert.match(f.get('starts-preview').textContent,/valid IANA/);
    f.dom.window.close();
});

test('edit repeated time, repeated zone conversions, unchanged save keeps microseconds', async()=>{
    const f=await setup(true);
    assert.equal(f.get('starts-occurrence').value,'later');
    assert.match(f.get('starts-at').value,/01:30:12/);
    for(const zone of ['UTC','Asia/Kolkata','America/Chicago']) await f.change('schedule-zone',zone,'change');
    assert.equal(f.get('starts-occurrence').value,'later');
    f.get('announcement-form').dispatchEvent(new f.dom.window.Event('submit',{cancelable:true}));await tick();
    const saved=f.requests.find(r=>r.options.method==='PUT');
    assert.ok(saved);
    assert.equal(saved.payload.starts_at.local_time,'2026-11-01T01:30:12.123456');
    assert.equal(saved.payload.starts_at.occurrence,'later');
    assert.equal(saved.payload.ends_at.local_time,'2026-11-01T02:30:12.654321');
    assert.equal(saved.options.headers['X-CSRF-Token'],'token');
    assert.equal(f.navigation.href,'/admin/announcements');
    f.dom.window.close();
});

test('invalid schedules cannot save; changed end and start sent as local values for server validation', async()=>{
    const f=await setup(true);
    await f.change('starts-at','2026-03-08T02:30');
    f.get('announcement-form').dispatchEvent(new f.dom.window.Event('submit',{cancelable:true}));await tick();
    assert.equal(f.requests.some(r=>r.options.method==='PUT'),false);
    assert.match(f.get('announcement-error').textContent,/Resolve/);
    await f.change('starts-at','2026-07-15T09:00');
    await f.change('ends-at','2026-07-15T10:00');
    f.get('announcement-form').dispatchEvent(new f.dom.window.Event('submit',{cancelable:true}));await tick();
    const saved=f.requests.find(r=>r.options.method==='PUT');
    assert.equal(saved.payload.starts_at.timezone,'America/Chicago');
    assert.match(saved.payload.ends_at.local_time,/2026-07-15T10:00/);
    f.dom.window.close();
});

 test('shared picker edits announcement wall time, with occurrence controls only for ambiguity',async()=>{
    const f=await setup(true);
    assert.equal(f.get('starts-at').type,'hidden');
    assert.equal(f.get('starts-occurrence').closest('.occurrence-field').hidden,false);
    const picker=f.get('starts-at').closest('.date-picker');
    const [hour,minute]=picker.querySelectorAll('.date-picker-time select');
    hour.value='03';minute.value='45';minute.dispatchEvent(new f.dom.window.Event('change'));await tick();
    assert.match(f.get('starts-preview').textContent,/09:45 UTC/);
    assert.equal(f.get('starts-occurrence').closest('.occurrence-field').hidden,true);
    await f.change('starts-at-date','2026-03-08');
    hour.value='02';minute.value='30';minute.dispatchEvent(new f.dom.window.Event('change'));await tick();
    assert.match(f.get('starts-preview').textContent,/does not exist/);
    assert.equal(f.get('starts-occurrence').closest('.occurrence-field').hidden,true);
    f.dom.window.close();
});
