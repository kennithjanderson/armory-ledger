"""Public route and escaped repository notes with no Settings or application DB imports."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from httpx import ASGITransport, AsyncClient
from jinja2 import Environment, FileSystemLoader
from app.services.changelog_service import load_changelog

ROOT = Path(__file__).resolve().parents[1]

class ChangelogTests(unittest.TestCase):
    def test_source_order_release_date_and_missing_metadata(self):
        records = load_changelog()
        self.assertEqual([r['version'] for r in records], ['0.1.5','0.1.4','0.1.3','0.1.2','0.1.1','0.1.0'])
        self.assertTrue(records[0]['unreleased'])
        self.assertIsNone(records[0]['date'])
        self.assertEqual(sum(r['version']=='0.1.4' for r in records), 1)
        self.assertTrue(records[1]['unreleased'])
        self.assertEqual(records[1]['date'].isoformat(), '2026-10-22')
        self.assertFalse(records[2]['unreleased'])
        self.assertEqual(records[2]['date'].isoformat(), '2026-10-15')
        with TemporaryDirectory() as folder:
            path=Path(folder)/'notes.json'
            self.assertEqual(load_changelog(path),[])
            path.write_text('{bad');self.assertEqual(load_changelog(path),[])
            path.write_text(json.dumps([{'version':'0.1.1','date':'bad','added':[]},{'version':'0.1.3'},{'version':'bad'}]))
            records=load_changelog(path)
            self.assertEqual(records[0]['version'],'0.1.3')
            self.assertIsNone(records[1]['date']);self.assertEqual(records[1]['sections'],[])

    def test_public_actual_route_base_footer_and_safe_content(self):
        env=Environment(loader=FileSystemLoader(ROOT/'app/templates'),autoescape=True)
        rendering=ModuleType('app.main_templates');rendering.templates=Jinja2Templates(env=env)
        config=ModuleType('app.core.config');config.settings=SimpleNamespace(app_name='Test',app_version='0.1.3',
            armory_operator_name=None,armory_support_email=None,armory_support_url=None)
        with patch.dict(sys.modules,{m.__name__:m for m in [rendering,config]}):
            spec=importlib.util.spec_from_file_location('test_changelog_router',ROOT/'app/api/changelog.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            about_spec=importlib.util.spec_from_file_location('test_public_about_router',ROOT/'app/api/about.py')
            about_module=importlib.util.module_from_spec(about_spec);about_spec.loader.exec_module(about_module)
        app=FastAPI();app.include_router(module.router);app.include_router(about_module.router)
        session_data = {}
        @app.middleware('http')
        async def session(request,call_next):
            request.scope['session']=session_data.copy()
            return await call_next(request)
        @app.get('/static/{path:path}',name='static')
        def static(path): return {}
        async def request(path="/changelog"):
            async with AsyncClient(transport=ASGITransport(app=app),base_url='https://example.test') as client:
                return await client.get(path)
        response=asyncio.run(request())
        self.assertEqual(response.status_code,200)
        self.assertIn('Unreleased draft',response.text)
        self.assertIn('Release date not set.',response.text)
        self.assertIn('<time datetime="2026-10-15">2026-10-15</time>',response.text)
        self.assertIn('v0.1.4 — Scheduled', response.text)
        self.assertNotIn('v0.1.4 — Unreleased draft', response.text)
        self.assertIn('Scheduled release: <time datetime="2026-10-22">2026-10-22</time>',response.text)
        self.assertIn('href="/changelog"',response.text)
        self.assertIn('Sign in',response.text);self.assertNotIn('Logout',response.text)
        self.assertIn('href="/auth/login">Sign in</a>',response.text)
        self.assertNotIn('class="user-menu"',response.text)
        self.assertIn('class="login-footer"',response.text)
        self.assertNotIn('class="app-footer"',response.text)
        self.assertNotIn('id="system-status"',response.text)
        self.assertNotIn('id="local-clock"',response.text)
        login_html = env.get_template('login.html').render(
            app_name='Test', app_version='0.1.3', url_for=lambda *a, **kw: '/static/' + kw['path'])
        import re
        self.assertEqual(re.search(r'<footer.*?</footer>',response.text,re.S).group(),
                         re.search(r'<footer.*?</footer>',login_html,re.S).group())
        anonymous_about=asyncio.run(request('/about'))
        self.assertEqual(anonymous_about.status_code,200)
        self.assertIn('Privacy and access',anonymous_about.text)
        self.assertIn('class="login-footer"',anonymous_about.text)
        self.assertIn('href="/auth/login">Sign in</a>',anonymous_about.text)
        self.assertIn('class="public-nav"',anonymous_about.text)
        self.assertNotIn('This installation',anonymous_about.text)
        self.assertNotIn('Logout',anonymous_about.text)
        self.assertNotIn('id="system-status"',anonymous_about.text)
        config.settings.armory_operator_name='Operator <Test>'
        config.settings.armory_support_email='support@example.invalid'
        config.settings.armory_support_url='https://example.invalid/support'
        configured_about=asyncio.run(request('/about'))
        self.assertIn('Operator &lt;Test&gt;',configured_about.text)
        self.assertIn('mailto:support@example.invalid',configured_about.text)
        self.assertIn('href="https://example.invalid/support"',configured_about.text)
        session_data['user'] = {'id':'test-user-id','email':'test@example.invalid',
                                'name':'Test <User>','is_admin':False}
        signed_in = asyncio.run(request())
        self.assertEqual(signed_in.status_code,200)
        self.assertIn('class="app-footer"',signed_in.text)
        self.assertNotIn('class="login-footer"',signed_in.text)
        self.assertIn('id="system-status"',signed_in.text)
        self.assertIn('id="local-clock"',signed_in.text)
        self.assertIn('About / Privacy',signed_in.text)
        self.assertIn('Test &lt;User&gt;',signed_in.text)
        self.assertIn('class="user-menu"',signed_in.text)
        self.assertNotIn('>Sign in</a>',signed_in.text)
        for target in ['/dashboard','/firearms','/ammunition','/accessories','/range','/settings','/auth/logout']:
            self.assertIn(f'href="{target}"',signed_in.text)
        self.assertNotIn('href="/admin"',signed_in.text)
        signed_about=asyncio.run(request('/about'))
        self.assertEqual(signed_about.status_code,200)
        self.assertIn('Test &lt;User&gt;',signed_about.text)
        self.assertIn('class="app-footer"',signed_about.text)
        self.assertIn('id="system-status"',signed_about.text)
        self.assertNotIn('>Sign in</a>',signed_about.text)
        self.assertEqual(re.search(r'<nav class="app-nav".*?</nav>',signed_about.text,re.S).group(),
                         re.search(r'<nav class="app-nav".*?</nav>',signed_in.text,re.S).group())
        session_data['user']['is_admin'] = True
        self.assertIn('href="/admin"',asyncio.run(request()).text)
        session_data.clear()
        malicious=[{'version':'1.0.0','date':None,'unreleased':False,'sections':[('Added',['<script>alert(1)</script>','[link](javascript:alert(1))'])]}]
        with patch.object(module,'load_changelog',return_value=malicious):
            html=asyncio.run(request()).text
        self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>alert(1)',html)
        self.assertNotIn('href="javascript:',html);self.assertIn('Release date not recorded.',html)
        with patch.object(module,'load_changelog',return_value=[]):
            self.assertIn('Release notes are not available yet.',asyncio.run(request()).text)
        main=(ROOT/'app/main.py').read_text()
        self.assertIn('app.include_router(changelog_router)',main)
        self.assertFalse(module.router.dependencies)
