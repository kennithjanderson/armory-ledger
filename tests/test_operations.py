"""Synthetic operational tests: temporary storage/SQLite and mocked PostgreSQL/SMTP."""
from datetime import datetime, timedelta, timezone
import base64
import importlib.util
import io
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import sys
import tarfile
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from cryptography.fernet import Fernet
from app.models.user import User
from app.models.notification import SystemSetting, NotificationEvent, NotificationRecipient

ROOT=Path(__file__).resolve().parents[1]


def load(name, path):
    spec=importlib.util.spec_from_file_location(name, ROOT/path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.test_key=base64.urlsafe_b64encode(bytes(range(32))).decode('ascii')
        self.config=SimpleNamespace(armory_backup_dir=self.temp.name,armory_backup_max_bytes=1024*1024,
            armory_timezone='UTC',app_name='Armory Ledger',app_version='0.1.4',armory_secret_key=Fernet.generate_key().decode(),
            armory_backup_encryption_key=self.test_key)
        self.engine=create_engine('sqlite:///:memory:')
        for model in (User,SystemSetting,NotificationEvent,NotificationRecipient): model.__table__.create(self.engine)
        self.factory=sessionmaker(self.engine,expire_on_commit=False); self.addCleanup(self.engine.dispose)
        config=ModuleType('app.core.config'); config.settings=self.config
        session=ModuleType('app.db.session'); session.SessionLocal=self.factory; session.engine=self.engine
        self.modules=patch.dict(sys.modules,{'app.core.config':config,'app.db.session':session}); self.modules.start(); self.addCleanup(self.modules.stop)
        self.backup=load('operations_backup','app/services/backup_service.py')
        self.mail=load('operations_mail','app/services/notification_service.py')
        self.module_patch=patch.dict(sys.modules,{'app.services.notification_service':self.mail}); self.module_patch.start();self.addCleanup(self.module_patch.stop)
        self.updates=load('operations_updates','app/services/update_service.py')
        self.storage=self.backup.store()
        with self.factory() as db:
            self.admin=User(oidc_subject='admin',email='admin@example.test',display_name='Admin',is_admin=True)
            self.admin2=User(oidc_subject='admin2',email='two@example.test',display_name='Two',is_admin=True)
            self.ordinary=User(oidc_subject='ordinary',email='user@example.test',display_name='User',is_admin=False)
            db.add_all([self.admin,self.admin2,self.ordinary]);db.commit()

    def fake_dump(self,*args):
        Path(args[-1]).write_bytes(b'PGDMPsynthetic')

    def test_backup_schema_check_requires_current_migration_head(self):
        with self.engine.begin() as connection:
            connection.exec_driver_sql('CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)')
            connection.exec_driver_sql('INSERT INTO alembic_version VALUES (?)', (self.backup.SCHEMA,))
        self.backup.schema_check()
        with self.engine.begin() as connection:
            connection.exec_driver_sql('UPDATE alembic_version SET version_num = ?', ('d914b7ce203a',))
        with self.assertRaisesRegex(ValueError, 'Database schema does not match'):
            self.backup.schema_check()

    def test_latest_image_poll_is_daily_admin_only_and_deduplicated(self):
        from datetime import datetime, timedelta, timezone
        first=datetime(2026,10,17,12,tzinfo=timezone.utc)
        self.config.app_version='0.1.3'
        self.configure_mail()
        with patch.object(self.updates,'image_version',return_value='0.1.4') as poll:
            self.assertTrue(self.updates.check_if_due(first))
            poll.assert_called_once_with()
            self.assertFalse(self.updates.check_if_due(first+timedelta(hours=23)))
            self.assertEqual(poll.call_count,1)
            self.assertTrue(self.updates.check_if_due(first+timedelta(days=1)))
            self.assertEqual(poll.call_count,2)
        with self.factory() as db:
            events=db.query(NotificationEvent).filter_by(kind='update_available').all()
            self.assertEqual(len(events),1)
            event=events[0]
            self.assertEqual(event.scope,'admin')
            self.assertEqual(event.severity,'info')
            self.assertEqual(event.action,'https://github.com/kennithjanderson/armory-ledger/releases/tag/v0.1.4')
            recipients=db.query(NotificationRecipient).filter_by(event_id=event.id).all()
            self.assertEqual({row.user_id for row in recipients},{self.admin.id,self.admin2.id})
            self.assertTrue(all(row.in_app and row.email_state=='pending' for row in recipients))
            self.assertEqual(db.get(SystemSetting,'upstream_image_update_check').value['latest_version'],'0.1.4')
        self.config.app_version='0.1.4'
        with patch.object(self.updates,'image_version',return_value='0.1.4'):
            self.assertTrue(self.updates.check_if_due(first+timedelta(days=2)))
        with self.factory() as db:
            event=db.query(NotificationEvent).filter_by(kind='update_available').one()
            self.assertTrue(event.resolved)
            recipients=db.query(NotificationRecipient).filter_by(event_id=event.id).all()
            self.assertTrue(all(row.read_at is not None for row in recipients))
            self.assertTrue(all(row.email_state=='cancelled' for row in recipients))

    def test_registry_latest_tag_reads_linux_amd64_image_version_label(self):
        class JsonResponse(io.BytesIO):
            status=200
            def __enter__(self): return self
            def __exit__(self,*args): self.close()
        payloads=[
            {'token':'anonymous-pull-token'},
            {'manifests':[{'platform':{'os':'linux','architecture':'amd64'},'digest':'sha256:manifest'}]},
            {'config':{'digest':'sha256:config'}},
            {'config':{'Labels':{'org.opencontainers.image.version':'0.1.4'}}},
        ]
        requests=[]
        def respond(request,timeout):
            requests.append(request)
            self.assertEqual(timeout,self.updates.REQUEST_TIMEOUT)
            return JsonResponse(json.dumps(payloads.pop(0)).encode())
        with patch.object(self.updates,'urlopen',side_effect=respond):
            self.assertEqual(self.updates.image_version(),'0.1.4')
        self.assertIn('/manifests/latest',requests[1].full_url)
        self.assertEqual(requests[2].get_header('Authorization'),'Bearer anonymous-pull-token')
        self.assertIn('/manifests/sha256:manifest',requests[2].full_url)
        self.assertIn('/blobs/sha256:config',requests[3].full_url)

    def test_update_check_failure_is_throttled_and_equal_version_is_silent(self):
        from datetime import datetime, timedelta, timezone
        first=datetime(2026,10,17,12,tzinfo=timezone.utc)
        self.config.app_version='0.1.3'
        with patch.object(self.updates,'image_version',side_effect=TimeoutError):
            self.assertTrue(self.updates.check_if_due(first))
            self.assertFalse(self.updates.check_if_due(first+timedelta(hours=2)))
        with self.factory() as db:
            self.assertEqual(db.query(NotificationEvent).filter_by(kind='update_available').count(),0)
            self.assertEqual(db.get(SystemSetting,'upstream_image_update_check').value['error'],'TimeoutError')
        self.config.app_version='0.1.4'
        with patch.object(self.updates,'image_version',return_value='0.1.4'):
            self.assertTrue(self.updates.check_if_due(first+timedelta(days=1)))
        with self.factory() as db:
            self.assertEqual(db.query(NotificationEvent).filter_by(kind='update_available').count(),0)

    def create(self,kind):
        with patch.object(self.backup,'schema_check'),patch.object(self.backup,'pg_command',side_effect=self.fake_dump):
            return self.backup.create_backup(kind,self.storage)

    def test_retention_types_zero_and_invalid(self):
        schedule=self.storage.schedule();schedule['retention']=3;self.storage.put('schedule',schedule)
        automatic=[self.create('automatic') for _ in range(3)]
        manual=self.create('manual');pre=self.create('pre-restore')
        self.assertEqual(len(self.storage.records()),5)
        self.assertTrue(all(self.storage.path(i).exists() for i in automatic))
        newest=self.create('automatic');self.assertEqual(self.backup.prune(self.storage),[])
        self.assertFalse(self.storage.path(automatic[0]).exists())
        for identifier in [*automatic[1:],manual,pre,newest]:self.assertTrue(self.storage.path(identifier).exists())
        schedule['retention']=0;self.storage.put('schedule',schedule);self.create('automatic')
        count=len(self.storage.records());self.backup.prune(self.storage);self.assertEqual(len(self.storage.records()),count)
        for value in (-1,'7',True):
            with self.assertRaises(ValueError):self.backup.validate_schedule({**schedule,'retention':value})

    def test_concurrent_store_initialization_is_serialized(self):
        with tempfile.TemporaryDirectory() as root:
            with ThreadPoolExecutor(max_workers=16) as pool:
                stores=list(pool.map(lambda _:self.backup.Store(root),range(64)))
            self.assertTrue(all(store.root==Path(root) for store in stores))
            self.assertEqual(stores[0].schedule()['enabled'],False)
            self.assertEqual(stores[0].jobs(),[])
            self.assertEqual((Path(root)/'catalogue-init.lock').stat().st_mode & 0o777,0o600)

    def test_invalid_archives_and_failed_backup_do_not_delete(self):
        identifier=self.create('automatic')
        path=Path(self.temp.name)/'invalid.tar'
        with tarfile.open(path,'w') as archive:
            member=tarfile.TarInfo('../escape');member.size=1;archive.addfile(member,io.BytesIO(b'x'))
        with self.assertRaises(ValueError):self.backup.validate_archive(path)
        with patch.object(self.backup,'schema_check'),patch.object(self.backup,'pg_command',side_effect=OSError('disk')):
            with self.assertRaises(OSError):self.backup.create_backup('manual',self.storage)
        self.assertTrue(self.storage.path(identifier).exists());self.assertFalse(list(Path(self.temp.name).glob('*.partial')))

    def test_aes256_gcm_creation_download_decrypt_and_wrong_key_fail_closed(self):
        import asyncio
        from uuid import UUID
        identifier=self.create('manual'); encrypted=self.storage.path(identifier)
        original=encrypted.read_bytes()
        self.assertTrue(original.startswith(self.backup.ENVELOPE_MAGIC))
        self.assertNotIn(b'PGDMP',original)
        self.assertEqual(encrypted.stat().st_mode & 0o777,0o600)
        self.assertFalse(list(Path(self.temp.name).glob('*.tar')))
        self.assertFalse(list(Path(self.temp.name).glob('stage-*')))
        self.assertFalse(list(Path(self.temp.name).glob('decrypt-*')))
        with tempfile.TemporaryDirectory(dir=self.temp.name) as folder:
            plaintext=Path(folder)/'archive.tar'
            self.backup.decrypt_archive(encrypted,plaintext)
            with tarfile.open(plaintext) as archive:
                self.assertEqual(archive.extractfile('database.dump').read(),b'PGDMPsynthetic')
            modified=Path(folder)/'modified.armorybackup'
            corrupted=bytearray(original);corrupted[-1]^=1;modified.write_bytes(corrupted)
            with self.assertRaises(self.backup.BackupAuthenticationError):self.backup.validate_archive(modified,self.storage)
        self.assertEqual(self.backup.validate_archive(encrypted,self.storage)['app_version'],'0.1.4')

        api=load('operations_api','app/api/operations.py')
        with patch.object(api.backup,'store',return_value=self.storage):
            response=api.download(UUID(identifier))
            async def body(): return b''.join([chunk async for chunk in response.body_iterator])
            self.assertEqual(asyncio.run(body()),original)
            self.assertEqual(response.media_type,'application/octet-stream')
            self.assertIn('.armorybackup',response.headers['content-disposition'])

        self.config.armory_backup_encryption_key=base64.urlsafe_b64encode(bytes(range(1,33))).decode('ascii')
        with self.factory() as db: user_count=db.query(User).count()
        orphan=str(__import__('uuid').uuid4())
        self.storage.path(orphan).write_bytes(original)
        self.storage.reconcile()
        self.assertTrue(self.storage.path(orphan).exists())
        self.assertNotIn(orphan,{row['id'] for row in self.storage.records()})
        with self.assertRaises(self.backup.BackupAuthenticationError):self.backup.validate_archive(encrypted,self.storage)
        with patch.object(self.backup,'create_backup') as create,patch.object(self.backup,'restore_database') as restore:
            with self.assertRaises(self.backup.BackupAuthenticationError):self.backup.restore_backup(identifier,self.storage)
            create.assert_not_called();restore.assert_not_called()
        self.assertEqual(encrypted.read_bytes(),original)
        self.assertEqual(self.storage.record(identifier)['status'],'valid')
        with self.factory() as db: self.assertEqual(db.query(User).count(),user_count)
        self.storage.path(orphan).unlink()

    def test_backup_creation_requires_valid_encryption_key_before_database_access(self):
        with patch.object(self.backup,'schema_check') as schema,patch.object(self.backup,'pg_command') as dump:
            for key in (None,'','not-base64',base64.urlsafe_b64encode(b'short').decode('ascii')):
                self.config.armory_backup_encryption_key=key
                with self.assertRaises(self.backup.BackupKeyError):self.backup.create_backup('manual',self.storage)
            schema.assert_not_called();dump.assert_not_called()

    def test_restore_preflight_and_rollback(self):
        identifier=self.create('manual')
        with patch.object(self.backup,'create_backup',side_effect=RuntimeError('pre-restore failed')),patch.object(self.backup,'restore_database') as restore:
            with self.assertRaises(RuntimeError):self.backup.restore_backup(identifier,self.storage)
            restore.assert_not_called()
        before=self.create('pre-restore')
        with patch.object(self.backup,'create_backup',return_value=before),patch.object(self.backup,'restore_database',side_effect=[RuntimeError('injected'),None]) as restore,patch.object(self.backup,'reconcile_outbox'):
            with self.assertRaisesRegex(RuntimeError,'original database recovered'):self.backup.restore_backup(identifier,self.storage)
        self.assertEqual(restore.call_count,2);self.assertFalse(self.storage.get('maintenance'))
        self.assertEqual(self.storage.get('recovery')['state'],'rolled_back')
        self.assertTrue(self.storage.path(before).exists())

    def test_schedule_dst_and_durable_coordination(self):
        schedule={'enabled':True,'hour':2,'minute':30,'timezone':'America/Chicago','retention':7}
        result=self.backup.next_run(schedule,datetime(2026,3,8,6,tzinfo=timezone.utc))
        self.assertEqual(result.day,9)
        self.storage.put('schedule',schedule)
        self.assertEqual(self.backup.Store(self.temp.name).schedule(),schedule)
        with self.backup.lock('worker',storage=self.storage):
            with self.assertRaises(self.backup.Busy):
                with self.backup.lock('worker',storage=self.storage):pass
        self.storage.enqueue('manual')
        with self.assertRaises(self.backup.Busy):self.storage.enqueue('automatic')

    def test_event_recipients_preferences_read_and_revocation(self):
        with self.factory() as db:
            admin=db.get(User,self.admin.id);admin.backup_success_email=True
            other=db.get(User,self.admin2.id);other.backup_success_in_app=True;db.commit()
        self.mail.backup_event('backup_completed','success')
        self.mail.backup_event('backup_failed','failure')
        with self.factory() as db:
            self.assertEqual(self.mail.notices(db,self.ordinary)['items'],[])
            a=self.mail.notices(db,self.admin);b=self.mail.notices(db,self.admin2)
            self.assertEqual(len(a['items']),1);self.assertEqual(len(b['items']),2)
            self.mail.mark_read(db,self.admin2,__import__('uuid').UUID(b['items'][0]['id']))
            unread=self.mail.notices(db,self.admin2,unread_only=True)
            self.assertEqual(len(unread['items']),1)
            self.mail.mark_read(db,self.admin)
            self.assertEqual(self.mail.notices(db,self.admin)['unread'],0)
            self.assertEqual(self.mail.notices(db,self.admin,unread_only=True)['items'],[])
            self.assertEqual(self.mail.notices(db,self.admin2)['unread'],1)
            with self.assertRaises(ValueError):self.mail.mark_read(db,self.admin,__import__('uuid').UUID(b['items'][0]['id']))
            self.admin.is_admin=False
            self.assertEqual(self.mail.notices(db,self.admin)['items'],[])

    def test_severity_retention_and_incident_resolution(self):
        now=datetime.now(timezone.utc)
        fixtures=[
            ('old-error','error',91,True),('old-warning','warning',31,True),
            ('old-info','info',8,True),('old-success','success',8,True),
            ('unresolved-error','error',120,False),('unresolved-warning','warning',45,False),
            ('recent-error','error',89,True),
        ]
        with self.factory() as db:
            for key,severity,age,resolved in fixtures:
                event=NotificationEvent(event_key=key,kind='synthetic',scope='admin',severity=severity,
                    title=key,message='Synthetic test event',updated_at=now-timedelta(days=age),resolved=resolved)
                db.add(event);db.flush()
                db.add(NotificationRecipient(event_id=event.id,user_id=self.admin.id,in_app=True,
                    read_at=None,email_state='disabled'))
            db.commit()
        self.mail.retain_history()
        with self.factory() as db:
            remaining={event.event_key for event in db.scalars(select(NotificationEvent))}
        self.assertEqual(remaining,{'unresolved-error','unresolved-warning','recent-error'})

    def test_successful_backup_resolves_prior_backup_failures(self):
        self.mail.backup_event('backup_failed','failure-before-recovery')
        with self.factory() as db:
            failure=db.scalar(select(NotificationEvent).where(NotificationEvent.event_key=='failure-before-recovery'))
            self.assertFalse(failure.resolved)
        self.mail.backup_event('backup_completed','success-after-recovery')
        with self.factory() as db:
            failure=db.scalar(select(NotificationEvent).where(NotificationEvent.event_key=='failure-before-recovery'))
            self.assertTrue(failure.resolved)

    def test_cleanup_grouping_and_resolution(self):
        self.mail.backup_event('cleanup_failed','first');self.mail.backup_event('cleanup_failed','second')
        self.mail.backup_event('cleanup_failed','second')
        with self.factory() as db:
            events=db.scalars(select(NotificationEvent)).all();self.assertEqual(len(events),1);self.assertEqual(events[0].occurrences,2)
            self.mail.mark_read(db,self.admin)
        self.mail.backup_event('cleanup_failed','third')
        with self.factory() as db:self.assertEqual(self.mail.notices(db,self.admin)['unread'],1)
        self.mail.resolve_cleanup();self.mail.backup_event('cleanup_failed','fourth')
        with self.factory() as db:self.assertEqual(len(db.scalars(select(NotificationEvent)).all()),2)

    def configure_mail(self):
        with self.factory() as db:
            self.mail.save_mail(db,{'enabled':True,'host':'localhost','port':2525,'security':'plain',
                'from_address':'armory@example.test','base_url':'https://example.test','password':'synthetic-password','username':'test'})

    def test_mail_masking_preservation_header_validation_and_captured_delivery(self):
        self.configure_mail()
        with self.factory() as db:
            original=self.mail.mail_config(db)['password_encrypted']
            self.assertNotIn('password_encrypted',self.mail.mail_config(db,public=True))
            self.mail.save_mail(db,{'from_name':'New name'})
            self.assertEqual(self.mail.mail_config(db)['password_encrypted'],original)
            with self.assertRaises(ValueError):self.mail.save_mail(db,{'from_name':'unsafe\r\nBcc: x'})
        self.mail.backup_event('backup_failed','mail-test')
        with patch.object(self.mail.smtplib,'SMTP') as smtp:
            self.mail.deliver_pending()
            self.assertEqual(smtp.return_value.__enter__.return_value.send_message.call_count,2)
        with self.factory() as db:
            self.assertTrue(all(r.email_state=='sent' for r in db.scalars(select(NotificationRecipient))))
            self.assertEqual(self.mail.notices(db,self.admin)['unread'],1)

    def test_revoked_recipient_no_queued_mail_and_restore_cancels(self):
        self.configure_mail();self.mail.backup_event('backup_failed','pending')
        with self.factory() as db:
            admin=db.get(User,self.admin.id);admin.is_admin=False;db.commit()
        with patch.object(self.mail.smtplib,'SMTP') as smtp:
            self.mail.deliver_pending();self.assertEqual(smtp.return_value.__enter__.return_value.send_message.call_count,1)
        self.mail.backup_event('backup_failed','historical')
        self.backup.reconcile_outbox()
        with self.factory() as db:
            self.assertFalse(db.scalar(select(NotificationRecipient).where(NotificationRecipient.email_state.in_(['pending','retry','sending']))))

    def test_manual_job_never_prunes_and_cleanup_warning_keeps_success(self):
        job={'id':self.storage.enqueue('manual'),'kind':'manual'}
        with patch.object(self.backup,'create_backup',return_value='synthetic'),patch.object(self.backup,'prune') as prune:
            self.backup.run_job(job,self.storage);prune.assert_not_called()
        self.assertEqual(self.storage.jobs()[0]['state'],'completed')
        job={'id':self.storage.enqueue('automatic'),'kind':'automatic'}
        with patch.object(self.backup,'create_backup',return_value='synthetic'),patch.object(self.backup,'prune',return_value=['old']):
            self.backup.run_job(job,self.storage)
        self.assertEqual(self.storage.jobs()[0]['state'],'completed')
        with self.factory() as db:
            kinds=list(db.scalars(select(NotificationEvent.kind)))
            self.assertEqual(kinds.count('backup_completed'),1);self.assertEqual(kinds.count('cleanup_failed'),1)

    def test_mail_failures_and_disabled_channel_preserve_notice(self):
        self.configure_mail();self.mail.backup_event('backup_failed','transient')
        with patch.object(self.mail.smtplib,'SMTP',side_effect=OSError('synthetic unreachable')):
            self.mail.deliver_pending()
        with self.factory() as db:
            rows=db.scalars(select(NotificationRecipient)).all()
            self.assertTrue(all(r.email_state=='retry' and r.attempts==1 for r in rows))
            self.assertEqual(self.mail.notices(db,self.admin)['unread'],1)
            self.mail.save_mail(db,{'enabled':False})
            self.assertTrue(all(r.email_state=='disabled' for r in db.scalars(select(NotificationRecipient))))
        self.configure_mail();self.mail.backup_event('backup_failed','permanent')
        with patch.object(self.mail.smtplib,'SMTP',side_effect=self.mail.smtplib.SMTPAuthenticationError(535,b'synthetic')):
            self.mail.deliver_pending()
        with self.factory() as db:
            self.assertTrue(any(r.email_state=='failed' for r in db.scalars(select(NotificationRecipient))))
            self.assertEqual(self.mail.notices(db,self.admin)['unread'],2)

    def test_archive_future_version_checksum_and_symlink_rejected(self):
        identifier=self.create('manual');source=self.storage.path(identifier)
        with tempfile.TemporaryDirectory(dir=self.temp.name) as folder:
            plaintext=Path(folder)/'plain.tar'
            self.backup.decrypt_archive(source,plaintext)
            with tarfile.open(plaintext) as archive:
                content={m.name:archive.extractfile(m).read() for m in archive}
        for mode in ('future','checksum','link'):
            changed=dict(content);manifest=json.loads(changed['manifest.json'])
            if mode=='future':manifest['app_version']='99.0.0'
            if mode=='checksum':manifest['inventory']['database.dump']['sha256']='0'*64
            changed['manifest.json']=json.dumps(manifest).encode()
            plain_target=Path(self.temp.name)/('invalid-'+mode+'.tar')
            with tarfile.open(plain_target,'w') as archive:
                for name,data in changed.items():
                    member=tarfile.TarInfo(name);member.size=len(data)
                    if mode=='link' and name=='database.dump':member.type=tarfile.SYMTYPE;member.linkname='/etc/passwd';member.size=0
                    archive.addfile(member,io.BytesIO(data))
            target=Path(self.temp.name)/('invalid-'+mode+'.armorybackup')
            self.backup.encrypt_archive(plain_target,target)
            with self.assertRaises(ValueError):self.backup.validate_archive(target,self.storage)

    def test_health_disabled_and_degraded(self):
        with patch.object(self.backup,'schema_check'):
            health=self.backup.health(self.storage)
            self.assertEqual(health['status'],'healthy');self.assertEqual(health['scheduler_status'],'disabled')
        with patch.object(self.backup,'schema_check',side_effect=RuntimeError('offline')):
            self.assertEqual(self.backup.health(self.storage)['status'],'degraded')

    def test_admin_operational_status_is_sanitized_and_admin_only(self):
        api=load('operations_api_status','app/api/operations.py')
        checks={'status':'healthy','storage':'writable','encryption':'ready','scheduler_status':'disabled',
                'maintenance':False,'recovery':{'state':'restored'}}
        mail={'enabled':True,'host':'smtp.private.test','from_address':'hidden@example.test',
              'password_set':True,'key_configured':True}
        with self.factory() as db, patch.object(api.backup,'health',return_value=checks), patch.object(api.notices,'mail_config',return_value=mail):
            result=api.operational_status(db)
        self.assertEqual(result,{'database':'connected','backups':{
            'status':'healthy','storage':'writable','encryption':'ready','scheduler':'disabled',
            'maintenance':'clear','recovery':'last recovery: restored'},
            'email':'enabled; live delivery not tested'})
        self.assertNotIn('smtp.private.test',json.dumps(result))
        self.assertNotIn('hidden@example.test',json.dumps(result))
        self.assertNotIn('password',json.dumps(result))
        self.assertTrue(any(dependency.dependency is api.require_admin for dependency in api.admin.dependencies))

    def test_settings_page_and_notification_preferences_are_authenticated_and_user_owned(self):
        api=load('operations_api_settings','app/api/operations.py')
        request=SimpleNamespace(session={})
        with patch.object(api,'csrf_token',return_value='csrf'),patch.object(api.templates,'TemplateResponse',return_value='rendered') as render:
            self.assertEqual(api.settings_page(request,self.ordinary),'rendered')
        self.assertEqual(render.call_args.kwargs['name'],'settings.html')
        self.assertTrue(any(dependency.dependency is api.get_current_user for dependency in api.user_routes.dependencies))

        payload={'ammo_notifications_in_app':True,'ammo_notifications_email':True}
        with self.factory() as db:
            ordinary=db.get(User,self.ordinary.id)
            standard_payload=api.list_notices(SimpleNamespace(session={}),0,False,ordinary,db)
            self.assertEqual(set(standard_payload['preferences']),
                {'ammo_notifications_in_app','ammo_notifications_email'})
            api.preferences(payload,ordinary,db)
            self.assertTrue(ordinary.ammo_notifications_in_app)
            self.assertTrue(ordinary.ammo_notifications_email)
            with self.assertRaises(api.HTTPException):
                api.preferences({'success_in_app':True,'success_email':True},ordinary,db)
            self.assertFalse(ordinary.backup_success_in_app)
            self.assertFalse(ordinary.backup_success_email)
            self.assertFalse(db.get(User,self.admin.id).backup_success_in_app)
            with self.assertRaises(api.HTTPException):
                api.preferences({**payload,'success_in_app':True,'success_email':True},ordinary,db)
            admin=db.get(User,self.admin.id)
            admin_payload=api.list_notices(SimpleNamespace(session={}),0,False,admin,db)
            self.assertIn('success_in_app',admin_payload['preferences'])
            self.assertIn('restore_initiated_email',admin_payload['preferences'])
            api.preferences({**payload,'success_in_app':True,'success_email':True,
                'restore_initiated_in_app':True,
                'restore_initiated_email':False},admin,db)
            self.assertTrue(admin.ammo_notifications_in_app)
            self.assertTrue(admin.ammo_notifications_email)
            self.assertTrue(admin.backup_success_in_app)
            self.assertTrue(admin.restore_initiated_in_app)
            self.assertFalse(admin.restore_initiated_email)

        dependency=api.preferences.__defaults__[0]
        self.assertIs(dependency.dependency,api.get_current_user)

    def test_restore_notice_survives_database_replacement_via_catalogue_queue(self):
        with self.factory() as db:
            admin=db.get(User,self.admin.id);admin.restore_initiated_in_app=True
            admin.restore_initiated_email=True
            second=db.get(User,self.admin2.id);second.restore_initiated_email=True
            ordinary=db.get(User,self.ordinary.id);ordinary.restore_initiated_in_app=True
            db.commit()
        selected=self.mail.restore_recipients()
        self.assertEqual({r['user_id'] for r in selected},{str(self.admin.id),str(self.admin2.id)})
        # Simulate PostgreSQL replacement after the worker snapshots recipients.
        def simulate_restore(*_args):
            with self.factory() as db:
                db.get(User,self.admin.id).restore_initiated_in_app=False
                db.get(User,self.admin.id).restore_initiated_email=False
                db.get(User,self.admin2.id).is_admin=False
                db.commit()
        job=self.storage.enqueue('restore','synthetic-backup')
        with patch.object(self.backup,'restore_backup',side_effect=simulate_restore):
            self.backup.run_job({'id':job,'kind':'restore','backup_id':'synthetic-backup'},self.storage)
        queued=self.storage.get('notice:'+job)
        self.assertEqual(queued['callback'],'restore_initiated')
        self.assertEqual(queued['args'][0],job)
        self.backup.flush_notices(self.storage)
        with self.factory() as db:
            event=db.scalar(select(NotificationEvent).where(NotificationEvent.event_key=='restore:'+job))
            self.assertEqual(event.severity,'warning')
            self.assertTrue(event.resolved)
            self.assertIn('initiated',event.title.lower())
            deliveries=db.scalars(select(NotificationRecipient).where(NotificationRecipient.event_id==event.id)).all()
            self.assertEqual(len(deliveries),1)
            self.assertEqual(deliveries[0].user_id,self.admin.id)
            self.assertTrue(deliveries[0].in_app)
            self.assertEqual(deliveries[0].email_state,'disabled')
        self.assertIsNone(self.storage.get('notice:'+job))

    def test_notification_email_uses_armory_branding_html_and_safe_plain_text(self):
        event=SimpleNamespace(severity='info',title='Test <notice>',
            message='A & B\n<script>alert(1)</script>',updated_at=datetime(2026,10,17,17,27,11,tzinfo=timezone.utc),
            action='/admin/email',kind='test_email')
        delivery=SimpleNamespace(test_recipient='recipient@example.test',id='delivery-id')
        config={**self.mail.DEFAULT_MAIL,'from_address':'armory@example.test',
            'base_url':'https://armory.example.test','from_name':'Armory Ledger'}
        message=self.mail.message_for(event,delivery,self.ordinary,config)
        self.assertEqual(message['Subject'],'[INFO] Test <notice>')
        self.assertEqual(message.get_content_type(),'multipart/alternative')
        plain=message.get_body(preferencelist=('plain',)).get_content()
        rich=message.get_body(preferencelist=('html',)).get_content()
        self.assertIn('ARMORY LEDGER — INFO NOTIFICATION',plain)
        self.assertIn('2026-10-17 17:27:11 UTC',plain)
        self.assertIn('https://armory.example.test/admin/email',plain)
        self.assertIn('#1c304d',rich)
        self.assertIn('#84383d',rich)
        self.assertIn('ARMORY LEDGER',rich)
        self.assertIn('href="https://armory.example.test/admin/email"',rich)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;',rich)
        self.assertNotIn('<script>',rich)

    def test_stale_jobs_orphans_and_missing_files_reconcile_safely(self):
        identifier=self.create('manual')
        self.storage.path(identifier).unlink()
        orphan=str(__import__('uuid').uuid4());self.storage.path(orphan).write_bytes(b'invalid')
        job=self.storage.enqueue('manual');self.storage.phase(job,'creating')
        self.storage.reconcile()
        records={r['id']:r for r in self.storage.records()}
        self.assertEqual(records[identifier]['status'],'missing')
        self.assertEqual(records[orphan]['kind'],'imported');self.assertEqual(records[orphan]['status'],'invalid')
        self.assertEqual(self.storage.jobs()[0]['state'],'failed')
        self.assertEqual(self.storage.get('notice:'+job)['args'],['backup_failed',job])

    def test_disabled_email_and_missing_address_diagnostic(self):
        self.mail.backup_event('backup_failed','disabled')
        with self.factory() as db:
            self.assertTrue(all(r.email_state=='disabled' for r in db.scalars(select(NotificationRecipient))))
            admin=db.get(User,self.admin.id);admin.email='';db.commit()
        self.configure_mail();self.mail.backup_event('backup_failed','missing-address')
        with self.factory() as db:
            rows=db.scalars(select(NotificationRecipient).where(NotificationRecipient.user_id==self.admin.id)).all()
            self.assertTrue(any(r.email_state=='failed' and 'no email' in r.diagnostic for r in rows))
            self.assertEqual(self.mail.notices(db,self.admin)['unread'],2)

    def test_independent_success_channels_and_one_email_per_cleanup_incident(self):
        self.configure_mail()
        with self.factory() as db:
            first=db.get(User,self.admin.id);first.backup_success_email=True
            second=db.get(User,self.admin2.id);second.backup_success_in_app=True;db.commit()
        self.mail.backup_event('backup_completed','personal-success')
        with patch.object(self.mail.smtplib,'SMTP') as smtp:
            self.mail.deliver_pending()
            self.assertEqual(smtp.return_value.__enter__.return_value.send_message.call_count,1)
        with self.factory() as db:
            self.assertEqual(self.mail.notices(db,self.admin)['items'],[])
            self.assertEqual(len(self.mail.notices(db,self.admin2)['items']),1)
            self.assertFalse(db.get(User,self.admin2.id).backup_success_email)
        with patch.object(self.mail.smtplib,'SMTP') as smtp:
            self.mail.backup_event('cleanup_failed','incident-one');self.mail.deliver_pending()
            self.mail.backup_event('cleanup_failed','incident-repeat');self.mail.deliver_pending()
            self.assertEqual(smtp.return_value.__enter__.return_value.send_message.call_count,2)
            self.mail.resolve_cleanup();self.mail.backup_event('cleanup_failed','incident-new');self.mail.deliver_pending()
            self.assertEqual(smtp.return_value.__enter__.return_value.send_message.call_count,4)

    def test_verified_oidc_denial_revokes_background_admin_and_session(self):
        import asyncio
        from unittest.mock import AsyncMock
        from fastapi import HTTPException
        authentication=ModuleType('app.core.auth')
        authentication.oauth=SimpleNamespace(authentik=SimpleNamespace(authorize_access_token=AsyncMock(return_value={
            'userinfo':{'sub':'admin','email':'admin@example.test','name':'Admin','groups':[]}})))
        dependencies=ModuleType('app.core.dependencies');dependencies.get_current_user=lambda:None
        with patch.dict(sys.modules,{'app.core.auth':authentication,'app.core.dependencies':dependencies}):
            routes=load('operations_auth','app/api/auth.py')
        request=SimpleNamespace(session={'user':{'id':str(self.admin.id),'is_admin':True}})
        with self.assertRaises(HTTPException) as failure:asyncio.run(routes.callback(request))
        self.assertEqual(failure.exception.status_code,403)
        self.assertEqual(request.session,{})
        with self.factory() as db:self.assertFalse(db.get(User,self.admin.id).is_admin)

    def test_starttls_failure_does_not_fall_back_or_send(self):
        self.configure_mail()
        with self.factory() as db:self.mail.save_mail(db,{'security':'starttls'})
        self.mail.backup_event('backup_failed','tls-failure')
        with patch.object(self.mail.smtplib,'SMTP') as smtp:
            connection=smtp.return_value.__enter__.return_value
            connection.starttls.side_effect=self.mail.ssl.SSLError('synthetic certificate failure')
            self.mail.deliver_pending()
            connection.send_message.assert_not_called()
            context=connection.starttls.call_args.kwargs['context']
            self.assertTrue(context.check_hostname)
            self.assertEqual(context.verify_mode,self.mail.ssl.CERT_REQUIRED)
        with self.factory() as db:
            self.assertTrue(all(r.email_state=='failed' for r in db.scalars(select(NotificationRecipient))))
