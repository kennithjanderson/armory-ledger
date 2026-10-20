const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const source = fs.readFileSync('app/static/js/notifications.js','utf8');
const tick = () => new Promise(resolve => setTimeout(resolve,20));

test('bell polls unread notices only, removes a read notice and supports Escape',async () => {
    const dom = new JSDOM('<button id="notification-toggle" class="notification-toggle" aria-expanded="false"></button><nav><a id="mobile-notifications-link" href="/notifications">Notifications</a></nav><section id="notification-panel" hidden><div id="notification-items"></div></section><button id="outside">Outside</button>',{runScripts:'outside-only',url:'https://example.test',pretendToBeVisual:true});
    const calls=[];let interval,unread=1,marked=false;
    dom.window.setInterval=(fn,delay)=>{interval=delay;return 1;};
    dom.window.fetch=async (url,options={})=>{calls.push([url,options]);if(options.method==='POST')marked=true;return {ok:true,json:async()=>({csrf_token:'test-token',unread:marked?0:unread,preferences:{},items:marked?[]:[{id:'synthetic',severity:'error',title:'<img src=x onerror=bad>',message:'Private-safe summary',timestamp:'2026-10-16T00:00:00Z',read:false,action:'/admin/backups',occurrences:1}]})};};
    dom.window.eval(source);await tick();
    assert.equal(interval,30000);
    assert.ok(calls.some(([url])=>url==='/api/notifications?unread_only=true'));
    const toggle=dom.window.document.getElementById('notification-toggle');
    assert.equal(toggle.classList.contains('has-unread'),true);
    assert.match(toggle.getAttribute('aria-label'),/1 unread/);
    assert.equal(dom.window.document.getElementById('notification-count'),null);
    assert.equal(dom.window.document.querySelectorAll('img').length,0);
    toggle.click();
    assert.equal(dom.window.document.getElementById('notification-panel').hidden,false);
    assert.equal(calls.filter(([,o])=>o.method==='POST').length,0);
    dom.window.document.querySelector('.notification-row').click();
    assert.equal(dom.window.document.getElementById('notification-panel').hidden,false);
    dom.window.document.getElementById('outside').click();
    assert.equal(dom.window.document.getElementById('notification-panel').hidden,true);
    toggle.click();
    dom.window.document.dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:'Escape'}));
    assert.equal(toggle.getAttribute('aria-expanded'),'false');
    assert.equal(dom.window.document.activeElement,toggle);
    dom.window.document.querySelector('.notification-row button').click();await tick();
    assert.equal(calls.find(([,o])=>o.method==='POST')[1].headers['X-CSRF-Token'],'test-token');
    assert.equal(toggle.classList.contains('has-unread'),false);
    assert.equal(dom.window.document.querySelector('#notification-items').children.length,0);
    dom.window.close();
});

test('history keeps read items while the bell contains only unread items',async () => {
    const dom=new JSDOM('<button id="notification-toggle"></button><section id="notification-panel"><div id="notification-items"></div></section><div id="notifications-history"></div><button id="notifications-more"></button>',{runScripts:'outside-only',url:'https://example.test',pretendToBeVisual:true});
    let marked=false;
    const readItem={id:'read-one',severity:'info',title:'Already read',message:'History item',timestamp:'2026-10-16T00:00:00Z',read:true,action:'/notifications',occurrences:1};
    const unreadItem={id:'unread-one',severity:'warning',title:'Needs attention',message:'Unread item',timestamp:'2026-10-17T00:00:00Z',read:false,action:'/notifications',occurrences:1};
    dom.window.setInterval=()=>1;
    dom.window.fetch=async (url,options={})=>{
        if(options.method==='POST')marked=true;
        const bell=url.includes('unread_only=true');
        return {ok:true,json:async()=>({csrf_token:'token',unread:marked?0:1,preferences:{},items:bell?(marked?[]:[unreadItem]):[readItem,{...unreadItem,read:marked}]})};
    };
    dom.window.eval(source);await tick();
    assert.deepEqual(Array.from(dom.window.document.querySelectorAll('#notification-items .notification-row strong'),node=>node.textContent),['WARNING: Needs attention (unread)']);
    assert.equal(dom.window.document.querySelectorAll('#notifications-history .notification-row').length,2);
    dom.window.document.querySelector('#notifications-history .notification-row button').click();await tick();
    assert.equal(dom.window.document.querySelector('#notification-items').children.length,0);
    assert.equal(dom.window.document.querySelectorAll('#notifications-history .notification-row').length,2);
    dom.window.close();
});

test('desktop bell placement and mobile notification link ordering',() => {
    const template=fs.readFileSync('app/templates/base.html','utf8');
    const desktop=template.slice(template.indexOf('<nav class="app-nav"'),template.indexOf('</nav>',template.indexOf('<nav class="app-nav"')));
    assert.ok(desktop.indexOf('Shooting Log')<desktop.indexOf('notification-bell'));
    assert.ok(desktop.indexOf('notification-bell')<desktop.indexOf('class="user-menu"'));
    assert.doesNotMatch(desktop,/notification-count|>\s*Notifications\s*</);
    const mobile=template.slice(template.indexOf('<div class="mobile-navigation"'),template.indexOf('</div>',template.indexOf('<div class="mobile-navigation"')));
    assert.ok(mobile.indexOf('Shooting Log')<mobile.indexOf('mobile-notifications-link'));
    assert.ok(mobile.indexOf('mobile-notifications-link')<mobile.indexOf('{% if is_admin %}'));
    assert.ok(mobile.indexOf('mobile-notifications-link')<mobile.indexOf('Settings'));
});

test('notification popover uses the application surface and explicit visited-link colors',() => {
    const template=fs.readFileSync('app/templates/base.html','utf8');
    const styles=fs.readFileSync('app/static/css/armory.css','utf8');
    const panel=template.slice(template.indexOf('<section id="notification-panel"'),template.indexOf('</section>',template.indexOf('<section id="notification-panel"')));
    assert.match(panel,/notification-panel-heading/);
    assert.match(panel,/notification-panel-links/);
    assert.match(panel,/href="\/notifications"/);
    assert.match(panel,/href="\/settings"/);
    assert.match(styles,/#notification-panel[^\{]*\{[^}]*var\(--surface\)/);
    assert.match(styles,/\.notification-panel-links a,\s*\.notification-panel-links a:visited[^\{]*\{[^}]*color:\s*var\(--navy\)/);
    assert.match(styles,/\.notification-open-link,\s*\.notification-open-link:visited[^\{]*\{[^}]*color:\s*var\(--navy-muted\)/);
    assert.doesNotMatch(styles,/@media \(prefers-color-scheme: dark\) \{ #notification-panel/);
});

test('Settings hosts personal notification preferences and history links back to Settings',() => {
    const settings=fs.readFileSync('app/templates/settings.html','utf8');
    const history=fs.readFileSync('app/templates/notifications.html','utf8');
    assert.match(settings,/id="notification-preferences"/);
    assert.match(settings,/name="ammo_notifications_in_app"/);
    assert.match(settings,/name="ammo_notifications_email"/);
    assert.match(settings,/{% if is_admin %}[\s\S]*name="success_in_app"[\s\S]*name="success_email"[\s\S]*{% endif %}/);
    assert.match(settings,/name="restore_initiated_in_app"/);
    assert.match(settings,/name="restore_initiated_email"/);
    assert.match(settings,/{% if is_admin %}[\s\S]*restore_initiated_in_app[\s\S]*{% endif %}/);
    assert.match(settings,/href="\/notifications"/);
    assert.match(history,/href="\/settings"/);
    assert.doesNotMatch(history,/id="notification-preferences"/);
});

test('standard-user Settings persist only personal ammunition channels',async () => {
    const dom=new JSDOM('<button id="notification-toggle"></button><section id="notification-panel"><div id="notification-items"></div></section><form id="notification-preferences"><input type="checkbox" name="ammo_notifications_in_app" checked><input type="checkbox" name="ammo_notifications_email"><button>Save</button></form><span id="preferences-result"></span>',{runScripts:'outside-only',url:'https://example.test'});
    let saved;
    dom.window.fetch=async (url,options={})=>{
        if(options.method==='PUT') saved=JSON.parse(options.body);
        return {ok:true,json:async()=>({csrf_token:'user-token',unread:0,preferences:{ammo_notifications_in_app:true,ammo_notifications_email:false},items:[]})};
    };
    dom.window.setInterval=()=>1;
    dom.window.eval(source);await tick();
    dom.window.document.getElementById('notification-preferences').dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}));
    await tick();
    assert.deepEqual(saved,{ammo_notifications_in_app:true,ammo_notifications_email:false});
    assert.equal(dom.window.document.getElementById('preferences-result').textContent,'Preferences saved.');
    dom.window.close();
});

test('admin Settings loads and saves restore-initiated channel preferences',async () => {
    const dom=new JSDOM('<button id="notification-toggle"></button><section id="notification-panel"><div id="notification-items"></div></section><form id="notification-preferences"><input type="checkbox" name="ammo_notifications_in_app"><input type="checkbox" name="ammo_notifications_email"><input type="checkbox" name="success_in_app"><input type="checkbox" name="success_email"><input type="checkbox" name="restore_initiated_in_app"><input type="checkbox" name="restore_initiated_email"><button>Save</button></form><span id="preferences-result"></span>',{runScripts:'outside-only',url:'https://example.test',pretendToBeVisual:true});
    let saved;
    dom.window.fetch=async (url,options={})=>{
        if(options.method==='PUT') saved=JSON.parse(options.body);
        return {ok:true,json:async()=>({csrf_token:'admin-token',unread:0,items:[],preferences:{ammo_notifications_in_app:false,ammo_notifications_email:false,success_in_app:false,success_email:false,restore_initiated_in_app:true,restore_initiated_email:false}})};
    };
    dom.window.setInterval=()=>1;
    dom.window.eval(source);await tick();
    const form=dom.window.document.getElementById('notification-preferences');
    assert.equal(form.elements.restore_initiated_in_app.checked,true);
    assert.equal(form.elements.restore_initiated_email.checked,false);
    form.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}));await tick();
    assert.deepEqual(saved,{ammo_notifications_in_app:false,ammo_notifications_email:false,success_in_app:false,success_email:false,restore_initiated_in_app:true,restore_initiated_email:false});
    dom.window.close();
});

test('lot notification form validates threshold and saves owned settings with CSRF',async () => {
    const html='<form id="ammunition-notification-settings" data-endpoint="/ammunition/lot/notifications" data-csrf-token="lot-token"><input type="checkbox" name="low_inventory_notifications_enabled" checked><input type="number" name="low_inventory_threshold"><input type="checkbox" name="depleted_notifications_enabled" checked><button>Save</button></form><span id="ammunition-notification-result"></span>';
    const dom=new JSDOM(html,{runScripts:'outside-only',url:'https://example.test'});
    let saved;
    dom.window.fetch=async (url,options)=>{saved={url,options};return {ok:true};};
    dom.window.eval(fs.readFileSync('app/static/js/ammunition-notifications.js','utf8'));
    const form=dom.window.document.getElementById('ammunition-notification-settings');
    form.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}));
    assert.equal(saved,undefined);
    assert.match(dom.window.document.getElementById('ammunition-notification-result').textContent,/positive round threshold/);
    form.elements.low_inventory_threshold.value='50';
    form.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}));
    await tick();
    assert.equal(saved.url,'/ammunition/lot/notifications');
    assert.equal(saved.options.method,'PUT');
    assert.equal(saved.options.headers['X-CSRF-Token'],'lot-token');
    assert.deepEqual(JSON.parse(saved.options.body),{
        low_inventory_notifications_enabled:true,
        low_inventory_threshold:50,
        depleted_notifications_enabled:true,
    });
    assert.equal(dom.window.document.getElementById('ammunition-notification-result').textContent,'Lot notification settings saved.');
    dom.window.close();
});
