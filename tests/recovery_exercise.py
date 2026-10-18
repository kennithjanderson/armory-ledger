"""Explicit disposable-PostgreSQL recovery exercise; never part of discovery."""
import json
import base64
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
from unittest.mock import patch
from sqlalchemy import text
from app.core.config import settings
from app.db.session import engine, SessionLocal
from app.services import backup_service as backup
from app.services import notification_service as notice
from app.models.user import User
from app.models.notification import NotificationRecipient
from sqlalchemy import select


def main():
    assert os.environ.get('ARMORY_DISPOSABLE_POSTGRES')=='1'
    assert settings.postgres_db=='armory_recovery_test'
    assert settings.postgres_host.startswith('armory-v014-test-')
    import test_range_service
    fixture=test_range_service.RangeServiceTests()
    fixture.make_engine=lambda:engine
    fixture.setUp()
    fixture.create()
    fixture.owner.is_admin=True;fixture.db.commit();fixture.db.close()
    with SessionLocal() as db:
        notice.save_mail(db,{'enabled':True,'host':'localhost','port':2525,'security':'plain','from_address':'test@example.test','base_url':'https://example.test'})
    notice.backup_event('backup_failed','synthetic-pending')
    storage=backup.store()
    def inventory():
        with engine.connect() as connection:
            tables=['users','firearms','ammo_lots','ammo_inventory_transactions','range_sessions','range_session_ammo_usage','range_session_firearms','system_settings','notification_events']
            return {table:sorted(json.dumps(row[0],sort_keys=True,default=str) for row in connection.execute(text(f'SELECT to_jsonb(t) FROM {table} t'))) for table in tables}
    baseline=inventory()
    identifier=backup.create_backup('manual',storage)
    archive=storage.path(identifier)
    assert archive.name.endswith('.armorybackup')
    assert archive.read_bytes().startswith(backup.ENVELOPE_MAGIC)
    assert b'PGDMP' not in archive.read_bytes()
    with tempfile.TemporaryDirectory(dir=storage.root) as folder:
        plaintext=Path(folder)/'backup.tar'
        backup.decrypt_archive(archive,plaintext)
        with tarfile.open(plaintext) as stream:
            assert stream.extractfile('database.dump').read(5)==b'PGDMP'
    correct_key=settings.armory_backup_encryption_key
    settings.armory_backup_encryption_key=base64.urlsafe_b64encode(bytes(range(1,33))).decode('ascii')
    try:
        try: backup.restore_backup(identifier,storage)
        except backup.BackupAuthenticationError: pass
        else: raise AssertionError('Incorrect backup key was accepted')
        assert inventory()==baseline
        assert not any(row['kind']=='pre-restore' for row in storage.records())
    finally:
        settings.armory_backup_encryption_key=correct_key
    with engine.begin() as connection: connection.execute(text("UPDATE users SET display_name='synthetic changed'"))
    backup.restore_backup(identifier,storage)
    assert inventory()==baseline
    with SessionLocal() as db:
        assert all(r.email_state=='cancelled' for r in db.scalars(select(NotificationRecipient)))
    assert any(row['kind']=='pre-restore' for row in storage.records())
    # Inject a failure after live mutation and verify recovery of the immediate prior state.
    with engine.begin() as connection: connection.execute(text("UPDATE users SET display_name='rollback marker'"))
    before=inventory(); actual=backup.restore_database; calls=[]
    def interrupted(path, storage_arg=None):
        actual(path,storage_arg); calls.append(path)
        if len(calls)==1: raise RuntimeError('Synthetic post-mutation failure')
    with patch.object(backup,'restore_database',side_effect=interrupted):
        try: backup.restore_backup(identifier,storage)
        except RuntimeError: pass
        else: raise AssertionError('Injected failure was not reported')
    assert inventory()==before and storage.get('recovery')['state']=='rolled_back'
    # Clean installation using the same isolated DB, then exercise the offline CLI.
    engine.dispose()
    with engine.begin() as connection:
        connection.execute(text('DROP SCHEMA public CASCADE'));connection.execute(text('CREATE SCHEMA public'))
    subprocess.run(['alembic','upgrade','head'],check=True)
    subprocess.run(['python','-m','app.recovery',str(archive),'--confirm-replace-all-data'],check=True)
    assert inventory()==baseline
    assert storage.path(identifier).exists()
    assert backup.health(storage)['database_schema']=='ready'
    assert storage.schedule()['enabled'] is False
    # Reopen the catalogue and DB connection, as after restart.
    engine.dispose();assert backup.Store(storage.root).records();assert inventory()==baseline
    # Exercise the real ASGI stack after recovery with synthetic signed sessions.
    import asyncio
    import httpx
    from itsdangerous import TimestampSigner
    from app.main import app
    with SessionLocal() as db:
        admin=db.scalar(select(User).where(User.oidc_subject=='owner'))
        ordinary=db.scalar(select(User).where(User.oidc_subject=='other'))
        identities=[(str(admin.id),True),(str(ordinary.id),False)]
    async def http_checks():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://example.test') as client:
            response=await client.get('/health'); assert response.status_code==200 and response.json()['version']=='0.1.4'
            for user_identifier,is_admin in identities:
                session={'user':{'id':user_identifier,'is_admin':is_admin},'csrf_token':'synthetic-token','recovery_epoch':storage.get('epoch')}
                signed=TimestampSigner(settings.session_secret).sign(base64.b64encode(json.dumps(session).encode())).decode()
                client.cookies.set('armory_ledger_session',signed)
                for path in ['/admin/backups','/admin/backups/status','/admin/email','/admin/email/settings']:
                    response=await client.get(path); assert response.status_code==(200 if is_admin else 403),(path,response.status_code)
                response=await client.get('/api/notifications'); assert response.status_code==200
                if not is_admin: assert response.json()['items']==[]
                for method,path,payload in [
                    ('POST','/admin/backups',{}),('PUT','/admin/backups/schedule',{}),
                    ('POST','/admin/backups/import',{}),('DELETE',f'/admin/backups/{identities[0][0]}',{}),
                    ('POST',f'/admin/backups/{identities[0][0]}/restore',{}),('PUT','/admin/email/settings',{}),
                    ('POST','/admin/email/test',{})]:
                    response=await client.request(method,path,json=payload)
                    assert response.status_code==403,(path,response.status_code)
                if not is_admin:
                    response=await client.get(f'/admin/backups/{identities[0][0]}/download'); assert response.status_code==403
                else:
                    response=await client.get(f'/admin/backups/{identifier}/download')
                    assert response.status_code==200 and response.content==archive.read_bytes(), (response.status_code, response.headers.get('content-type'), len(response.content))
                    assert response.headers['content-type']=='application/octet-stream'
                    assert response.content.startswith(backup.ENVELOPE_MAGIC) and b'PGDMP' not in response.content
    asyncio.run(http_checks())
    print('PASS: AES-256-GCM archive creation/download/decryption, wrong-key rejection before database mutation, PostgreSQL restore round trip, clean-install offline recovery, inventory/account/settings relationships, pre-restore retention, post-mutation rollback, historical-mail cancellation, restart, health and protected HTTP routes')


if __name__=='__main__': main()
