"""Release orchestration tests: temporary Git only; no network, Docker or systemd jobs."""
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / 'tools/release'
sys.path.insert(0, str(TOOLS))
import common
import engine
import image_policy
import validation


class PrimitiveTests(unittest.TestCase):
    def test_version_and_dst_and_past(self):
        self.assertEqual(common.version('v0.1.3'), '0.1.3')
        for value in ['1.2', '01.2.3', '1.2.3;echo', '../1.2.3']:
            with self.assertRaises(common.ReleaseError): common.version(value)
        now = datetime(2025,1,1,tzinfo=timezone.utc)
        self.assertEqual(common.resolve_time('2026-01-15 09:00','America/Chicago',now=now),'2026-01-15T15:00:00+00:00')
        self.assertEqual(common.resolve_time('2026-07-15 09:00','America/Chicago',now=now),'2026-07-15T14:00:00+00:00')
        for value in ['2026-03-08 02:30','2026-11-01 01:30']:
            with self.assertRaises(common.ReleaseError): common.resolve_time(value,'America/Chicago',now=now)
        self.assertIn('07:30:00',common.resolve_time('2026-11-01 01:30','America/Chicago','later',now))
        for local, zone in [('invalid','UTC'),('2020-01-01 00:00','UTC'),('2026-10-15 08:00','bad/zone')]:
            with self.assertRaises(common.ReleaseError): common.resolve_time(local,zone,now=now)

    def test_monotonic_latest_and_minor_policy(self):
        self.assertFalse(image_policy.may_promote('0.1.3',['0.1.4']))
        self.assertFalse(image_policy.may_promote('0.1.3',[],{'version':'0.1.4'}))
        self.assertTrue(image_policy.may_promote('0.1.3',['0.2.0'],{'version':'0.1.2'},minor=True))
        self.assertFalse(image_policy.may_promote('0.1.3',['0.1.10'],minor=True))
        self.assertTrue(image_policy.may_promote('0.1.10',['0.1.9']))
        with self.assertRaises(common.ReleaseError): image_policy.may_promote('0.1.3',[],{'commit':'abc'})

    def test_scan_reports_locations_without_values_and_allowlist_is_exact(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); secret='gh'+'p_'+'x'*36
            path=root/'example.txt';path.write_text(secret+'\n')
            findings=common.scan_files(root)
            self.assertEqual(findings,[('example.txt',1,'github-token')])
            with self.assertRaises(common.ReleaseError) as caught: common.assert_scan(root)
            self.assertNotIn(secret,str(caught.exception))
            (root/'release-scan-allowlist.json').write_text(json.dumps({f'example.txt:github-token:{common.sha256(secret.encode())}':{'reason':'Synthetic noncredential fixture'}}))
            self.assertEqual(common.scan_files(root),[])
            path.write_text(secret+'changed');self.assertTrue(common.scan_files(root))
            (root/'.env').write_text('');self.assertIn(('.env',0,'runtime-or-key-file'),common.scan_files(root))

    def test_saved_notes_manual_auto_edit_and_missing_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'app/content').mkdir(parents=True)
            (root/'app/content/changelog.json').write_text(json.dumps([{'version':'0.1.3','added':['User-visible change']}]))
            auto=engine.choose_notes(root,'0.1.3',[], 'auto')
            self.assertIn('## New Features',auto);self.assertNotIn('Bug Fixes',auto)
            manual=root/'manual.md';manual.write_text('Approved custom notes\n')
            self.assertEqual(engine.choose_notes(root,'0.1.3',[],'manual',manual),'Approved custom notes\n')
            self.assertEqual(manual.read_text(),'Approved custom notes\n')
            self.assertIn('No release summary',common.release_notes(root,'0.1.4'))
            self.assertIn('Relevant commit',common.release_notes(root,'0.1.4',['Relevant commit']))
            def edit(args,**kwargs):
                Path(args[-1]).write_text('Edited draft\n')
                return type('Result',(),{'returncode':0})()
            with patch.dict(os.environ,{'EDITOR':'test-editor','VISUAL':''}),patch('subprocess.run',side_effect=edit):
                self.assertEqual(engine.choose_notes(root,'0.1.3',[],'edit'),'Edited draft\n')
            with patch('builtins.input',return_value='no'):
                with self.assertRaises(common.ReleaseError): engine.confirm('Publish?', 'YES')

    def test_github_release_pagination_and_network_failure(self):
        page = [{'tag_name':f'v0.0.{n}'} for n in range(100)]
        expected = {'tag_name':'v0.1.3','body':'saved notes'}
        with patch.object(engine,'run',side_effect=[json.dumps(page),json.dumps([expected])]) as calls:
            self.assertEqual(engine.github_release('owner/repo','v0.1.3'),expected)
            self.assertIn('page=2',calls.call_args.args[0][-1])
        with patch.object(engine,'run',side_effect=common.ReleaseError('Unavailable')):
            with self.assertRaises(common.ReleaseError):engine.github_release('owner/repo','v0.1.3')

    def test_timer_persistence_escaping_and_lock(self):
        service,timer=engine.timer_units(Path('/tmp/test space/v0.1.3'), '2026-10-15T14:00:00+00:00')
        self.assertIn('OnCalendar=2026-10-15 14:00:00 UTC',timer)
        self.assertIn('Persistent=true',timer);self.assertIn('OnBootSec=2min',timer)
        self.assertIn('OnUnitInactiveSec=5min',timer);self.assertIn('Restart=on-failure',service)
        self.assertIn('execute',service);self.assertNotIn('manual',service)
        self.assertEqual(engine.systemd_quote('/tmp/a%b'), '"/tmp/a%%b"')
        with tempfile.TemporaryDirectory() as root:
            with common.locked(root):
                with self.assertRaises(common.ReleaseError):
                    with common.locked(root): pass


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.repo=self.root/'repo';self.repo.mkdir()
        common.run(['git','init','-b','main',str(self.repo)])
        common.git(self.repo,'config','user.name','Synthetic Tester')
        common.git(self.repo,'config','user.email','tester@example.invalid')
        common.git(self.repo,'remote','add','origin','git@github.com:kennithjanderson/armory-ledger.git')
        (self.repo/'app/core').mkdir(parents=True);(self.repo/'app/content').mkdir(parents=True)
        (self.repo/'app/core/config.py').write_text('class Settings:\n    app_version: str = "0.1.3"\n')
        (self.repo/'app/content/changelog.json').write_text(json.dumps([{'version':'0.1.3','added':['Approved feature']}]))
        (self.repo/'.github/workflows').mkdir(parents=True)
        (self.repo/'.github/workflows/docker-publish.yml').write_text((TOOLS.parents[1]/'.github/workflows/docker-publish.yml').read_text())
        (self.repo/'tools/release').mkdir(parents=True)
        (self.repo/'tools/release/image_policy.py').write_text('# Synthetic policy presence; command tests mock publication')
        (self.repo/'feature.txt').write_text('original')
        common.git(self.repo,'add','.');common.git(self.repo,'commit','-m','Synthetic baseline')
        self.config={'repository':engine.DEFAULT_REPOSITORY,'state_dir':str(self.root/'state')}

    def test_validate_only_exact_selection_and_no_publication_on_success_or_failure(self):
        (self.repo/'feature.txt').write_text('selected working tree')
        (self.repo/'new.txt').write_text('selected untracked')
        (self.repo/'other.txt').write_text('unrelated staged')
        common.git(self.repo, 'add', 'other.txt')
        index = (self.repo/'.git/index').read_bytes()
        refs = common.git(self.repo, 'show-ref')
        commits = common.git(self.repo, 'rev-list', '--all')
        for fail in (False, True):
            archives = []
            def check(root, target, config, *, results):
                archives.append(root)
                self.assertEqual((root/'feature.txt').read_text(), 'selected working tree')
                self.assertEqual((root/'new.txt').read_text(), 'selected untracked')
                self.assertFalse((root/'other.txt').exists())
                results['python'] = 'failed' if fail else 'passed'
                if fail: raise common.ReleaseError('Synthetic validation failure')
            with patch.object(engine, 'validate', side_effect=check), \
                 patch.object(engine, 'confirm'), patch('builtins.print') as output, \
                 patch.object(engine, 'prepare', side_effect=AssertionError('prepare forbidden')), \
                 patch.object(engine, 'publish', side_effect=AssertionError('publish forbidden')), \
                 patch.object(engine, 'install_timer', side_effect=AssertionError('timer forbidden')), \
                 patch.object(engine, 'github_access', side_effect=AssertionError('GitHub forbidden')):
                if fail:
                    with self.assertRaises(common.ReleaseError):
                        engine.validate_only(self.repo, self.config, '0.1.3', ['feature.txt', 'new.txt'])
                else:
                    tree = engine.validate_only(self.repo, self.config, '0.1.3', ['feature.txt', 'new.txt'])
                    self.assertEqual(common.git(self.repo, 'show', tree+':new.txt'), 'selected untracked')
                self.assertTrue(any('Validation summary' in str(call) for call in output.call_args_list))
            self.assertTrue(archives)
            self.assertTrue(all(not path.exists() for path in archives))
            self.assertEqual((self.repo/'.git/index').read_bytes(), index)
            self.assertEqual(common.git(self.repo, 'show-ref'), refs)
            self.assertEqual(common.git(self.repo, 'rev-list', '--all'), commits)
            self.assertFalse((self.root/'state').exists())

    def test_validate_only_source_allowlist_scan_and_approval(self):
        # Use the actual approved detector and its exact source-path/hash exception.
        detector = self.repo/'tools/release/common.py'
        detector.write_bytes((TOOLS/'common.py').read_bytes())
        (self.repo/'release-scan-allowlist.json').write_bytes(
            (TOOLS.parents[1]/'release-scan-allowlist.json').read_bytes())
        (self.repo/'unrelated.txt').write_text('preserve staging')
        common.git(self.repo, 'add', 'unrelated.txt')
        paths = ['tools/release/common.py', 'release-scan-allowlist.json']
        index = (self.repo/'.git/index').read_bytes()
        refs = common.git(self.repo, 'show-ref')
        commits = common.git(self.repo, 'rev-list', '--all')
        def working_files():
            return {str(p.relative_to(self.repo)):p.read_bytes()
                    for p in self.repo.rglob('*')
                    if p.is_file() and '.git' not in p.relative_to(self.repo).parts}
        before = working_files()
        for answer in ('no', 'VALIDATE'):
            def validate_source(root, target, config, *, results):
                validation.static_validate(root, target)
                results['static'] = 'passed'
            with patch('builtins.input', return_value=answer) as approval, \
                 patch('builtins.print') as output, \
                 patch.object(engine, 'validate', side_effect=validate_source) as validator, \
                 patch.object(engine, 'publish', side_effect=AssertionError('No publication')), \
                 patch.object(engine, 'install_timer', side_effect=AssertionError('No timer')):
                if answer == 'no':
                    with self.assertRaises(common.ReleaseError):
                        engine.validate_only(self.repo, self.config, '0.1.3', paths)
                    validator.assert_not_called()
                else:
                    tree = engine.validate_only(self.repo, self.config, '0.1.3', paths)
                    validator.assert_called_once()
                    diff = common.git(self.repo, 'diff', '--no-ext-diff', '--no-textconv', 'HEAD', tree)
                    output.assert_any_call(diff)
                approval.assert_called_once()
                self.assertIn('VALIDATE', approval.call_args.args[0])
            self.assertEqual(working_files(), before)
            self.assertEqual((self.repo/'.git/index').read_bytes(), index)
            self.assertEqual(common.git(self.repo, 'show-ref'), refs)
            self.assertEqual(common.git(self.repo, 'rev-list', '--all'), commits)
            self.assertFalse((self.root/'state').exists())
        # An approved detector does not authorize sensitive content elsewhere.
        (self.repo/'unapproved.txt').write_text('gh'+'p_'+'x'*36+'\n')
        before = working_files()
        with patch('builtins.input') as approval, patch('builtins.print'), \
             patch.object(engine, 'validate') as validator:
            with self.assertRaisesRegex(common.ReleaseError, 'unapproved.txt.*github-token'):
                engine.validate_only(self.repo, self.config, '0.1.3', [*paths, 'unapproved.txt'])
            approval.assert_not_called()
            validator.assert_not_called()
        self.assertEqual(working_files(), before)
        self.assertEqual((self.repo/'.git/index').read_bytes(), index)
        self.assertEqual(common.git(self.repo, 'show-ref'), refs)
        self.assertFalse((self.root/'state').exists())

    def test_validate_only_cli_bypasses_notes_and_state_machine(self):
        from types import SimpleNamespace
        args = SimpleNamespace(repo=self.repo, version='0.1.3', dry_run=False,
                               validate_only=True, command='manual')
        with patch('builtins.input', side_effect=['feature.txt', '']), \
             patch('builtins.print'), patch.object(engine, 'validate_only') as check, \
             patch.object(engine, 'locked', side_effect=AssertionError('State lock forbidden')):
            engine.interactive(args)
        self.assertEqual(check.call_args.args[3], ['feature.txt'])

    def test_bulk_discovery_and_tree_cover_all_git_states(self):
        for name in ('deleted.txt', 'renamed.txt'):
            (self.repo/name).write_text(name)
        (self.repo/'.gitignore').write_text('ignored.txt\n')
        common.git(self.repo, 'add', '.')
        common.git(self.repo, 'commit', '-m', 'Synthetic bulk baseline')
        (self.repo/'feature.txt').write_text('modified')
        (self.repo/'deleted.txt').unlink()
        common.git(self.repo, 'mv', 'renamed.txt', 'new name.txt')
        (self.repo/'staged.txt').write_text('staged')
        common.git(self.repo, 'add', 'staged.txt')
        (self.repo/'staged.txt').write_text('working tree wins')
        (self.repo/'untracked.txt').write_text('untracked')
        (self.repo/'ignored.txt').write_text('ignored')
        index = (self.repo/'.git/index').read_bytes()
        expected = sorted(['feature.txt','deleted.txt','renamed.txt','new name.txt','staged.txt','untracked.txt'])
        self.assertEqual(engine.discover_changes(self.repo), expected)
        with patch.object(engine, 'confirm') as confirm, patch('builtins.print'):
            paths = engine.bulk_selection(self.repo)
        self.assertEqual(paths, expected)
        self.assertEqual(confirm.call_args.args[1], 'INCLUDE ALL CHANGES')
        tree = engine.selected_tree(self.repo, paths)
        self.assertEqual(common.git(self.repo, 'show', tree+':staged.txt'), 'working tree wins')
        names = common.git(self.repo, 'ls-tree', '-r', '--name-only', tree).splitlines()
        for absent in ('deleted.txt','renamed.txt','ignored.txt'): self.assertNotIn(absent,names)
        for present in ('new name.txt','untracked.txt'): self.assertIn(present,names)
        self.assertEqual((self.repo/'.git/index').read_bytes(),index)

    def test_bulk_cancellation_never_constructs_tree(self):
        from types import SimpleNamespace
        args = SimpleNamespace(repo=self.repo, version='0.1.3', dry_run=False,
                               validate_only=True, include_all_changes=True, command='manual')
        (self.repo/'new.txt').write_text('new')
        with patch('builtins.input', return_value='no'), patch('builtins.print'), \
             patch.object(engine, 'selected_tree') as tree, patch.object(engine, 'validate') as validator:
            with self.assertRaises(common.ReleaseError): engine.interactive(args)
        tree.assert_not_called(); validator.assert_not_called()
        self.assertFalse((self.root/'state').exists())

    def test_bulk_rejects_sensitive_symlink_and_submodule(self):
        for name, setup in [('.env.private', lambda p:p.write_text('synthetic')),
                            ('link', lambda p:p.symlink_to('feature.txt'))]:
            path = self.repo/name; setup(path)
            with patch('builtins.print'), patch.object(engine, 'confirm') as confirm:
                with self.assertRaises(common.ReleaseError): engine.bulk_selection(self.repo)
                confirm.assert_not_called()
            path.unlink()
        head = common.git(self.repo, 'rev-parse', 'HEAD')
        common.git(self.repo, 'update-index', '--add', '--cacheinfo', '160000', head, 'module')
        with patch('builtins.print'), patch.object(engine, 'confirm') as confirm:
            with self.assertRaises(common.ReleaseError): engine.bulk_selection(self.repo)
            confirm.assert_not_called()

    def test_bulk_flag_rejected_outside_preparation(self):
        for args in [('manual','--dry-run'), ('schedule','--validate-only'), ('execute',)]:
            with patch.object(sys, 'argv', ['engine.py', *args, '--include-all-changes']), \
                 patch('sys.stderr'), patch.object(engine, 'interactive') as interactive:
                with self.assertRaises(SystemExit) as error: engine.main()
                self.assertEqual(error.exception.code, 2)
                interactive.assert_not_called()

    def test_expected_tree_blocks_mismatch_and_source_changes(self):
        tree = common.git(self.repo, 'rev-parse', 'HEAD^{tree}')
        refs = common.git(self.repo, 'show-ref')
        index = (self.repo/'.git/index').read_bytes()
        with patch.object(engine, 'validate') as validator, patch.object(engine, 'make_candidate') as candidate:
            with self.assertRaisesRegex(common.ReleaseError, 'does not match'):
                engine.prepare(self.repo,self.config,'0.1.3',[],'auto',None,expected_tree='0'*40)
            with self.assertRaisesRegex(common.ReleaseError, 'does not match'):
                engine.validate_only(self.repo,self.config,'0.1.3',[],expected_tree='0'*40)
            validator.assert_not_called(); candidate.assert_not_called()
        self.assertFalse((self.root/'state').exists())
        def approval(message, word):
            if word == 'CREATE CANDIDATE':
                (self.repo/'feature.txt').write_text('changed during review')
        with patch.object(engine,'remote_tag',return_value=None), patch.object(engine,'github_access'), \
             patch.object(engine,'confirm',side_effect=approval), patch.object(engine,'validate',return_value={}), \
             patch.object(engine,'make_candidate') as candidate, patch('builtins.print'):
            with self.assertRaisesRegex(common.ReleaseError, 'source changed'):
                engine.prepare(self.repo,self.config,'0.1.3',['feature.txt'],'auto',None,expected_tree=tree)
            candidate.assert_not_called()
        self.assertEqual(common.git(self.repo, 'show-ref'), refs)
        self.assertEqual((self.repo/'.git/index').read_bytes(), index)

    def test_manual_and_scheduled_bulk_preparation_keep_approvals(self):
        from types import SimpleNamespace
        from contextlib import nullcontext
        (self.repo/'feature.txt').write_text('bulk-selected change')
        for command in ('manual', 'schedule'):
            args = SimpleNamespace(repo=self.repo, version='0.1.3', dry_run=False,
                validate_only=False, include_all_changes=True, command=command,
                expected_tree=engine.selected_tree(self.repo,['feature.txt']))
            answers = ['INCLUDE ALL CHANGES', 'auto']
            if command == 'schedule': answers += ['UTC','2099-10-15 09:00','']
            with patch('builtins.input',side_effect=answers), patch('builtins.print'), \
                 patch.object(engine,'locked',return_value=nullcontext()), \
                 patch.object(engine,'run',return_value='yes') as host, \
                 patch.object(engine,'prepare',side_effect=common.ReleaseError('Stop at preparation')) as prepare, \
                 patch.object(engine,'install_timer') as timer, patch.object(engine,'execute') as execute:
                with self.assertRaisesRegex(common.ReleaseError,'Stop at preparation'): engine.interactive(args)
                self.assertEqual(prepare.call_args.kwargs['expected_tree'],args.expected_tree)
                self.assertEqual(prepare.call_args.args[3],['feature.txt'])
                if command == 'schedule':
                    self.assertEqual(prepare.call_args.args[6], '2099-10-15T09:00:00+00:00')
                    self.assertEqual(host.call_args.args[0][0], 'loginctl')
                timer.assert_not_called(); execute.assert_not_called()

    def test_schedule_bulk_still_requires_future_time_and_lingering(self):
        from types import SimpleNamespace
        args = SimpleNamespace(repo=self.repo, version='0.1.3', dry_run=False,
            validate_only=False, include_all_changes=True, command='schedule', expected_tree=None)
        for local, linger in [('2000-01-01 09:00','yes'),('2099-10-15 09:00','no')]:
            with patch('builtins.input',side_effect=['INCLUDE ALL CHANGES','auto','UTC',local,'']), \
                 patch('builtins.print'), patch.object(engine,'run',return_value=linger), \
                 patch.object(engine,'prepare') as prepare, patch.object(engine,'install_timer') as timer:
                with self.assertRaises(common.ReleaseError): engine.interactive(args)
                prepare.assert_not_called(); timer.assert_not_called()

    def test_expected_tree_requires_full_hash(self):
        import argparse
        for value in ('abc123', 'v0.1.3', 'z'*40):
            with self.assertRaises(argparse.ArgumentTypeError): engine.expected_tree_sha(value)
        self.assertEqual(engine.expected_tree_sha('A'*40), 'a'*40)

    def test_matching_expected_tree_preserves_candidate_approval(self):
        tree = common.git(self.repo, 'rev-parse', 'HEAD^{tree}')
        words = []
        with patch.object(engine,'remote_tag',return_value=None), patch.object(engine,'github_access'), \
             patch.object(engine,'confirm',side_effect=lambda message,word:words.append(word)), \
             patch.object(engine,'validate',return_value={}), patch('builtins.print'):
            folder=engine.prepare(self.repo,self.config,'0.1.3',[],'auto',None,expected_tree=tree)
        self.assertEqual(engine.frozen_payload(folder)['tree'],tree)
        self.assertEqual(words[:2], ['VALIDATE','CREATE CANDIDATE'])
        self.assertTrue(words[-1].startswith('APPROVE 0.1.3 '))

    def prepare(self, paths=()):
        with patch.object(engine,'remote_tag',return_value=None),patch.object(engine,'github_access'),\
             patch.object(engine,'confirm'),patch.object(engine,'validate',return_value={'tests':'passed'}),patch('builtins.print'):
            return engine.prepare(self.repo,self.config,'0.1.3',list(paths),'auto',None)

    def test_selected_index_preserves_user_staging_and_untracked_and_pin(self):
        (self.repo/'feature.txt').write_text('approved')
        (self.repo/'unrelated.txt').write_text('leave alone')
        common.git(self.repo,'add','unrelated.txt')
        before=common.git(self.repo,'diff','--cached','--binary')
        folder=self.prepare(['feature.txt'])
        payload=engine.frozen_payload(folder)
        self.assertEqual(common.git(self.repo,'show',payload['sha']+':feature.txt'),'approved')
        self.assertNotIn('unrelated.txt',common.git(self.repo,'ls-tree','-r','--name-only',payload['sha']))
        self.assertEqual(common.git(self.repo,'diff','--cached','--binary'),before)
        common.git(self.repo,'add','feature.txt');common.git(self.repo,'commit','-m','Later main change')
        self.assertNotEqual(common.git(self.repo,'rev-parse','HEAD'),payload['sha'])
        self.assertEqual(engine.frozen_payload(folder)['sha'],payload['sha'])
        self.assertEqual(common.git(self.repo,'rev-parse','refs/armory/releases/'+payload['id']),payload['sha'])

    def test_no_pending_changes_is_valid_candidate_and_notes_tamper_fails(self):
        folder=self.prepare();self.assertEqual(engine.status(folder)['stage'],'approved')
        (folder/'notes.md').write_text('replaced')
        with self.assertRaisesRegex(common.ReleaseError,'notes changed'):engine.frozen_payload(folder)

    def test_validation_failure_or_existing_tag_stops_preparation(self):
        with patch.object(engine,'remote_tag',return_value='abc'):
            with self.assertRaises(common.ReleaseError):engine.prepare(self.repo,self.config,'0.1.3',[],'auto',None)
        with patch.object(engine,'remote_tag',side_effect=common.ReleaseError('Network unavailable')):
            with self.assertRaises(common.ReleaseError):engine.prepare(self.repo,self.config,'0.1.3',[],'auto',None)
        with patch.object(engine,'remote_tag',return_value=None),patch.object(engine,'github_access'),patch.object(engine,'confirm'),\
             patch.object(engine,'validate',side_effect=common.ReleaseError('validation failed')),patch('builtins.print'):
            with self.assertRaises(common.ReleaseError):engine.prepare(self.repo,self.config,'0.1.3',[],'auto',None)
        self.assertFalse(list((self.root/'state').glob('*/approval.json')))

    def test_timer_install_cancel_reschedule_are_explicit_and_tombstone_survives_restart(self):
        folder=self.prepare();engine.update(folder,'approved',when='2099-10-15T14:00:00+00:00',scheduled=True)
        with patch.object(Path,'home',return_value=self.root),patch.object(engine,'run') as commands:
            engine.install_timer(folder)
            self.assertTrue((self.root/'.config/systemd/user'/('armory-release-'+folder.name+'.timer')).exists())
            self.assertTrue(any('enable' in call.args[0] for call in commands.call_args_list))
            original=engine.frozen_payload(folder)
            with patch.object(engine,'confirm'):
                engine.manage(folder,'reschedule','2099-10-16T14:00:00+00:00')
            self.assertEqual(engine.frozen_payload(folder),original)
            engine.manage(folder,'cancel')
            self.assertTrue(engine.status(folder)['cancelled'])
        with patch.object(engine,'repository',side_effect=AssertionError('Must not publish')):
            engine.publish(folder)

    def publication_doubles(self, folder, interrupt=False):
        data={'tag':None,'release':None,'pushes':[], 'interrupted':False}
        payload=engine.frozen_payload(folder);real_git=engine.git
        def fake_git(repo,*args,**kwargs):
            if args[0]=='push': data['pushes'].append(args);return ''
            if args[0]=='ls-remote':return ''
            if args[0]=='tag' and '-a' in args:data['tag']=payload['sha'];return ''
            return real_git(repo,*args,**kwargs)
        def fake_run(args,**kwargs):
            if args[0]=='git' and 'push' in args:data['pushes'].append(args);return ''
            if args[:3]==['gh','release','create']:
                data['release']={'body':(folder/'notes.md').read_text(),'draft':False,'prerelease':False}
                if interrupt and not data['interrupted']:
                    data['interrupted']=True;raise common.ReleaseError('Connection interrupted after server commit')
                return ''
            raise AssertionError(args)
        return data, fake_git, fake_run

    def test_scheduled_pin_safe_retry_after_partial_publication_and_duplicate_execution(self):
        folder=self.prepare();engine.update(folder,'approved',scheduled=True,when='2020-01-01T00:00:00+00:00')
        payload=engine.frozen_payload(folder)
        (self.repo/'feature.txt').write_text('later development');common.git(self.repo,'add','feature.txt');common.git(self.repo,'commit','-m','Later development')
        data,fake_git,fake_run=self.publication_doubles(folder,interrupt=True)
        def validate_pin(root,target,config):
            self.assertEqual((Path(root)/'feature.txt').read_text(),'original')
        def verified(p,f):engine.update(f,'complete',container_verified=True)
        with patch.object(engine,'git',side_effect=fake_git),patch.object(engine,'run',side_effect=fake_run),\
             patch.object(engine,'local_tag',side_effect=lambda *a:data['tag']),patch.object(engine,'remote_tag',side_effect=lambda *a:data['tag']),\
             patch.object(engine,'github_access'),patch.object(engine,'github_release',side_effect=lambda *a:data['release']):
            with self.assertRaises(common.ReleaseError):engine.publish(folder,validate_pin,verified)
            engine.publish(folder,validate_pin,verified)
            count=len(data['pushes']);engine.publish(folder,validate_pin,verified);self.assertEqual(len(data['pushes']),count)
        self.assertTrue(engine.status(folder)['container_verified'])
        self.assertTrue(any(payload['sha'] in str(args) for args in data['pushes']))
        self.assertFalse(any('refs/heads/main' in str(args) for args in data['pushes']))
        self.assertEqual(engine.frozen_payload(folder)['notes_sha256'],payload['notes_sha256'])

    def test_failed_revalidation_never_publishes_and_does_not_replace_candidate(self):
        folder=self.prepare();original=engine.frozen_payload(folder)
        with patch.object(engine,'remote_tag',return_value=None),patch.object(engine,'github_access'),\
             patch.object(engine,'run',side_effect=AssertionError('No publication command allowed')):
            with self.assertRaisesRegex(common.ReleaseError,'failed validation'):
                engine.publish(folder,lambda *a:(_ for _ in ()).throw(common.ReleaseError('failed validation')))
        self.assertEqual(original,engine.frozen_payload(folder))

    def test_image_verification_checks_workflow_sha_digest_and_labels(self):
        folder=self.prepare();payload=engine.frozen_payload(folder);digest='sha256:'+'a'*64
        sha=payload['sha'];image='ghcr.io/'+payload['repository']
        def fake_run(args,**kwargs):
            if args[:2]==['gh','api']:
                return json.dumps({'workflow_runs':[{'id':1,'head_sha':sha,'head_branch':'v0.1.3','event':'release','status':'completed','conclusion':'success'}]})
            if args[:3]==['gh','run','download']:
                Path(args[-1],'release-receipt.json').write_text(json.dumps({'commit':sha,'version':'0.1.3','digest':digest}));return ''
            if args[1]=='pull':return ''
            return json.dumps([{'Config':{'Labels':{'org.opencontainers.image.revision':sha,'org.opencontainers.image.version':'0.1.3'}},'RepoDigests':[image+'@'+digest]}])
        with patch.object(engine,'run',side_effect=fake_run),patch('builtins.print'):
            engine.verify_image(payload,folder)
        self.assertEqual(engine.status(folder)['stage'],'complete')
        def wrong(args,**kw):
            result=fake_run(args,**kw)
            return result.replace(sha,'b'*40) if args[0]=='docker' and args[1]=='image' else result
        with patch.object(engine,'run',side_effect=wrong):
            with self.assertRaisesRegex(common.ReleaseError,'revision/version mismatch'):engine.verify_image(payload,folder)


    def test_pending_or_wrong_workflow_never_reports_full_success(self):
        folder=self.prepare();payload=engine.frozen_payload(folder)
        for record in [[],[{'id':1,'head_sha':payload['sha'],'head_branch':'v0.1.3','event':'release','status':'in_progress','conclusion':None}],
                       [{'id':2,'head_sha':'f'*40,'head_branch':'v0.1.3','event':'release','status':'completed','conclusion':'success'}]]:
            with patch.object(engine,'run',return_value=json.dumps({'workflow_runs':record})):
                with self.assertRaises(common.ReleaseError):engine.verify_image(payload,folder)
            self.assertNotEqual(engine.status(folder)['stage'],'complete')

    def test_runner_tamper_or_changed_reference_is_rejected(self):
        folder=self.prepare();(folder/'engine/common.py').write_text('# altered runner')
        with self.assertRaisesRegex(common.ReleaseError,'runner changed'):engine.frozen_payload(folder)

    def test_manual_push_uses_pinned_sha_and_tag_reachable(self):
        folder=self.prepare();payload=engine.frozen_payload(folder)
        data,fake_git,fake_run=self.publication_doubles(folder)
        with patch.object(engine,'git',side_effect=fake_git),patch.object(engine,'run',side_effect=fake_run),\
             patch.object(engine,'local_tag',side_effect=lambda *a:data['tag']),patch.object(engine,'remote_tag',side_effect=lambda *a:data['tag']),\
             patch.object(engine,'github_access'),patch.object(engine,'github_release',return_value=None):
            engine.publish(folder,lambda *a:None,lambda *a:None)
        self.assertEqual(data['tag'],payload['sha'])
        self.assertTrue(any(payload['sha']+':refs/heads/main' in str(args) for args in data['pushes']))
        self.assertTrue(engine.status(folder)['github_published'])
        self.assertFalse(engine.status(folder)['container_verified'])

    def test_future_schedule_reboot_check_has_no_publication(self):
        folder=self.prepare();engine.update(folder,'scheduled',when='2099-01-01T00:00:00+00:00',scheduled=True)
        with patch.object(engine,'repository',side_effect=AssertionError('Not due')):
            engine.publish(folder)

    def test_candidate_creation_cancel_preserves_unapproved_state(self):
        calls=[]
        def approval(message,word):
            calls.append(word)
            if word.startswith('APPROVE'):raise common.ReleaseError('Cancelled')
        with patch.object(engine,'remote_tag',return_value=None),patch.object(engine,'github_access'),\
             patch.object(engine,'confirm',side_effect=approval),patch.object(engine,'validate',return_value={}),patch('builtins.print'):
            with self.assertRaises(common.ReleaseError):engine.prepare(self.repo,self.config,'0.1.3',[],'auto',None)
        folder=next(path for path in (self.root/'state').iterdir() if path.is_dir())
        self.assertFalse(engine.status(folder)['approved'])
        with self.assertRaisesRegex(common.ReleaseError,'approval'):engine.publish(folder)

class ValidationIsolationTests(unittest.TestCase):
    def test_disposable_validation_builds_before_env_files_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'tests').mkdir();(root/'tests/example.test.cjs').write_text('')
            commands=[]
            def command(args,**kwargs):
                commands.append(args)
                if args[1]=='build':
                    self.assertFalse((root/'.release-app.env').exists())
                    self.assertFalse((root/'.release-db.env').exists())
                if args[0]=='python-test':
                    self.assertEqual(kwargs['env']['ARMORY_DISPOSABLE_POSTGRES'],'1')
                    self.assertIn('127.0.0.1:54321/release_test',kwargs['env']['ARMORY_TEST_POSTGRES_URL'])
                if args[1]=='port':return '127.0.0.1:54321'
                return ''
            with patch.object(validation,'static_validate'),patch.object(validation,'run',side_effect=command),patch.object(validation,'check_http'):
                result=validation.validate(root,'0.1.3',{'test_python':'python-test'})
            self.assertEqual(result['build'],'passed')
            self.assertEqual(result['migrations'],'passed')
            self.assertEqual(result['cleanup'],'passed')
            self.assertFalse(any('compose' in args for args in commands))
            self.assertEqual(len([args for args in commands if args[1:3]==['rm','-fv']]),2)
            self.assertFalse((root/'.release-app.env').exists())
            self.assertFalse((root/'.release-db.env').exists())
            networks = [cmd for cmd in commands if cmd[1:3] == ['network', 'create']]
            self.assertEqual(len(networks), 1)
            network = networks[0][-1]
            self.assertTrue(network.startswith('armory-release-test-'))
            self.assertEqual(networks[0], ['docker', 'network', 'create', '--driver', 'bridge', network])
            containers = [cmd for cmd in commands if cmd[1] == 'run']
            self.assertEqual(len(containers), 2)
            self.assertEqual([cmd[cmd.index('-p')+1] for cmd in containers],
                             ['127.0.0.1::5432', '127.0.0.1::8000'])
            for cmd in containers:
                self.assertEqual(cmd[cmd.index('--network')+1], network)
                self.assertIn(['docker', 'rm', '-fv', cmd[cmd.index('--name')+1]], commands)
            self.assertIn(['docker', 'network', 'rm', network], commands)
            self.assertIn(['docker', 'image', 'rm', network+':candidate'], commands)

    def test_failed_test_stops_before_app_start_and_cleans_disposable_resources(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);commands=[]
            def command(args,**kwargs):
                commands.append(args)
                if args[0]=='python-test':raise common.ReleaseError('tests failed')
                if args[1]=='port':return '127.0.0.1:54321'
                return ''
            with patch.object(validation,'static_validate'),patch.object(validation,'run',side_effect=command):
                with self.assertRaises(common.ReleaseError):validation.validate(root,'0.1.3',{'test_python':'python-test'})
            self.assertEqual(len([args for args in commands if args[1]=='run']),1)
            self.assertFalse((root/'.release-db.env').exists())
            self.assertFalse((root/'.release-app.env').exists())
            network = next(cmd[-1] for cmd in commands if cmd[1:3] == ['network', 'create'])
            self.assertIn(['docker', 'rm', '-fv', network+'-db'], commands)
            self.assertIn(['docker', 'network', 'rm', network], commands)
            self.assertIn(['docker', 'image', 'rm', network+':candidate'], commands)

    def test_migration_failure_and_interruption_both_clean_up(self):
        for interrupt in (False, True):
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder); (root/'tests').mkdir()
                (root/'tests/example.test.cjs').write_text('// synthetic')
                commands = []; results = {}
                def command(args, **kwargs):
                    commands.append(args)
                    if args[1] == 'port': return '127.0.0.1:54321'
                    if args[1] == 'exec' and 'python' in args:
                        if interrupt: raise KeyboardInterrupt()
                        raise common.ReleaseError('Migration heads differ')
                    return ''
                with patch.object(validation, 'static_validate'), \
                     patch.object(validation, 'check_http'), \
                     patch.object(validation, 'run', side_effect=command):
                    with self.assertRaises(KeyboardInterrupt if interrupt else common.ReleaseError):
                        validation.validate(root, '0.1.3', {}, results=results)
                self.assertEqual(results['migrations'], 'failed')
                self.assertEqual(results['cleanup'], 'passed')
                self.assertEqual(len([cmd for cmd in commands if cmd[1:3] == ['rm','-fv']]), 2)
                self.assertFalse((root/'.release-app.env').exists())

    def test_cleanup_failure_is_reported_and_remaining_cleanup_attempted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); commands = []; results = {}
            def command(args, **kwargs):
                commands.append(args)
                if args[0] == 'python-test': raise common.ReleaseError('tests failed')
                if args[1] == 'port': return '127.0.0.1:54321'
                if args[1:3] == ['rm', '-fv'] and args[-1].endswith('-db'):
                    raise common.ReleaseError('cleanup unavailable')
                return ''
            with patch.object(validation, 'static_validate'), patch.object(validation, 'run', side_effect=command):
                with self.assertRaisesRegex(common.ReleaseError, 'Disposable cleanup failed'):
                    validation.validate(root, '0.1.3', {'test_python':'python-test'}, results=results)
            self.assertEqual(results['python'], 'failed')
            self.assertEqual(results['javascript'], 'not run')
            self.assertEqual(results['cleanup'], 'failed')
            self.assertTrue(any(cmd[1:3] == ['network', 'rm'] for cmd in commands))
            self.assertTrue(any(cmd[1:3] == ['image', 'rm'] for cmd in commands))
            self.assertFalse((root/'.release-db.env').exists())

    def test_workflow_serializes_and_pins_commit_and_receipt(self):
        workflow=(TOOLS.parents[1]/'.github/workflows/docker-publish.yml').read_text()
        for value in ['queue: max','cancel-in-progress: false','ref: ${{ github.event.release.tag_name }}',
                      'org.opencontainers.image.revision=${{ env.RELEASE_SHA }}','release-receipt.json']:
            self.assertIn(value,workflow)
        self.assertNotIn('type=raw,value=latest',workflow)
        self.assertIn('image_policy.py promote',workflow)


if __name__ == '__main__':
    unittest.main()
