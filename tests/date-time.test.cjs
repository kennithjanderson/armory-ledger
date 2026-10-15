const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
const script=fs.readFileSync('app/static/js/date-time.js','utf8');
async function setup(html) {
    const dom=new JSDOM(html,{runScripts:'outside-only'});
    await new Promise(resolve=>dom.window.document.addEventListener('DOMContentLoaded',resolve,{once:true}));
    dom.window.eval(script);dom.window.document.dispatchEvent(new dom.window.Event('DOMContentLoaded'));
    return {dom,doc:dom.window.document,api:dom.window.ArmoryDateTime};
}
test('historical calendar direct month/year, leap dates, keyboard and date-only roundtrip',async()=>{
    const {dom,doc,api}=await setup('<label for="acquired">Acquired date</label><input id="acquired" type="date" required value="1945-01-01">');
    const input=doc.getElementById('acquired');assert.equal(input.value,'1945-01-01');assert.equal(input.type,'text');
    doc.querySelector('.date-picker-open').click();
    const year=doc.querySelector('[aria-label="Year"]'),month=doc.querySelector('[aria-label="Month"]');
    year.value='1904';year.dispatchEvent(new dom.window.Event('input'));
    month.value='2';month.dispatchEvent(new dom.window.Event('change'));
    const day=doc.querySelector('[data-date="1904-02-29"]');assert.ok(day);day.click();
    assert.equal(input.value,'1904-02-29');assert.equal(doc.activeElement,input);
    input.value='1900-02-29';input.dispatchEvent(new dom.window.Event('input'));assert.equal(input.checkValidity(),false);
    input.value='2000-02-29';input.dispatchEvent(new dom.window.Event('input'));assert.equal(input.checkValidity(),true);
    doc.querySelector('.date-picker-open').click();
    doc.querySelector('[data-date="2000-02-01"]').dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
    assert.equal(doc.activeElement.dataset.date,'2000-02-02');
    doc.activeElement.dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
    assert.equal(doc.querySelector('.date-picker-panel').hidden,true);
    assert.equal(api.validDate('2026-10-14'),true);
    dom.window.close();
});
test('24-hour controls support boundary times without date reselection and preserve unchanged seconds',async()=>{
    const {dom,doc,api}=await setup('<label for="start">Start</label><input id="start" type="datetime-local" required value="2026-10-14T08:30:12.123">');
    const input=doc.getElementById('start');assert.equal(input.value,'2026-10-14T08:30:12.123');
    const [hour,minute]=doc.querySelectorAll('.date-picker-time select');
    assert.equal(hour.options.length,25);assert.equal(minute.options.length,61);
    for(const value of ['00:00','08:30','12:00','23:59']) {
        [hour.value,minute.value]=value.split(':');minute.dispatchEvent(new dom.window.Event('change'));
        assert.equal(input.value,`2026-10-14T${value}`);
    }
    input.value='2026-11-01T01:30:12.123';api.refresh(input);
    assert.equal(hour.value,'01');assert.equal(minute.value,'30');assert.equal(doc.getElementById('start-date').value,'2026-11-01');
    assert.doesNotMatch(doc.body.textContent,/\b(AM|PM)\b/);
    dom.window.close();
});
test('month precision, removal/reconfiguration and required empty input',async()=>{
    const {dom,doc,api}=await setup('<input id="date" type="month" required value="1950-06">');
    const input=doc.getElementById('date');assert.equal(input.value,'1950-06');
    doc.querySelector('.date-picker-open').click();doc.querySelector('.date-picker-days button').click();assert.equal(input.value,'1950-06');
    api.remove(input);input.type='date';input.value='1950-06-01';api.enhance(input);
    input.value='1950-06-02';input.dispatchEvent(new dom.window.Event('input'));assert.equal(input.checkValidity(),true);
    input.value='';input.dispatchEvent(new dom.window.Event('input'));assert.equal(input.checkValidity(),false);
    assert.equal(doc.querySelectorAll('.date-picker').length,1);dom.window.close();
});
test('shared display always uses 24-hour local time and seconds only when requested',async()=>{
    const {dom,api}=await setup('');
    for(const [h,m] of [[0,0],[8,30],[12,0],[23,59]]) {
        const date=new dom.window.Date(2026,9,14,h,m,7);
        const expected=`2026-10-14 ${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}`;
        assert.equal(api.formatLocal(date),expected);assert.equal(api.formatLocal(date,true),expected+':07');
    }
    dom.window.close();
});
