"""Whole-instance recovery. Operational catalogue deliberately survives DB restore."""
from contextlib import contextmanager
import base64
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import threading
import uuid
from zoneinfo import ZoneInfo
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from sqlalchemy import text
from app.core.config import settings

UTC = timezone.utc
SCHEMA = 'a47c91e2d563'
TYPES = {'automatic', 'manual', 'pre-restore', 'imported'}
ENVELOPE_MAGIC = b'ARMORY-BACKUP-AES256GCM\x01'
NONCE_SIZE = 12
TAG_SIZE = 16
ENVELOPE_OVERHEAD = len(ENVELOPE_MAGIC) + NONCE_SIZE + TAG_SIZE


def now():
    return datetime.now(UTC)


class Busy(RuntimeError):
    pass


class BackupKeyError(ValueError):
    pass


class BackupAuthenticationError(ValueError):
    pass


class BackupFormatError(ValueError):
    pass


_catalogue_init_guard = threading.Lock()
_catalogue_initialized = set()


def initialize_catalogue(root):
    """Create the operational SQLite schema once, coordinating app processes."""
    root = Path(root)
    identity = str(root.resolve())
    if identity in _catalogue_initialized:
        return
    with _catalogue_init_guard:
        if identity in _catalogue_initialized:
            return
        lock_fd = os.open(root/'catalogue-init.lock', os.O_CREAT|os.O_RDWR, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            with sqlite3.connect(root/'catalogue.sqlite', timeout=30) as db:
                db.execute('PRAGMA busy_timeout=30000')
                db.executescript('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS backups (id TEXT PRIMARY KEY, kind TEXT NOT NULL, created TEXT NOT NULL,
                version TEXT NOT NULL, size INTEGER NOT NULL, status TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, kind TEXT NOT NULL, backup_id TEXT,
                state TEXT NOT NULL, phase TEXT NOT NULL, created TEXT NOT NULL, error TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_job ON jobs((1)) WHERE state IN ('queued','running');''')
            (root/'catalogue.sqlite').chmod(0o600)
            _catalogue_initialized.add(identity)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)


def encryption_key():
    configured = settings.armory_backup_encryption_key
    if not isinstance(configured, str) or not configured:
        raise BackupKeyError('ARMORY_BACKUP_ENCRYPTION_KEY is required for backup and restore operations')
    try:
        key = base64.b64decode(configured, altchars=b'-_', validate=True)
    except (ValueError, TypeError) as exc:
        raise BackupKeyError('ARMORY_BACKUP_ENCRYPTION_KEY must be URL-safe base64 encoding of exactly 32 bytes') from exc
    if len(key) != 32 or base64.urlsafe_b64encode(key).decode('ascii') != configured:
        raise BackupKeyError('ARMORY_BACKUP_ENCRYPTION_KEY must be URL-safe base64 encoding of exactly 32 bytes')
    return key


def encrypt_archive(source, target, key=None):
    key = key if key is not None else encryption_key()
    nonce = secrets.token_bytes(NONCE_SIZE)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(ENVELOPE_MAGIC)
    target = Path(target)
    created = False
    try:
        with Path(source).open('rb') as reader, target.open('xb') as writer:
            created = True
            target.chmod(0o600)
            writer.write(ENVELOPE_MAGIC + nonce)
            while chunk := reader.read(1024 * 1024):
                writer.write(encryptor.update(chunk))
            writer.write(encryptor.finalize())
            writer.write(encryptor.tag)
            writer.flush()
            os.fsync(writer.fileno())
    except Exception:
        if created: target.unlink(missing_ok=True)
        raise


def decrypt_archive(source, target, key=None):
    key = key if key is not None else encryption_key()
    source, target = Path(source), Path(target)
    created = False
    try:
        size = source.stat().st_size
        if size < ENVELOPE_OVERHEAD or size > settings.armory_backup_max_bytes + ENVELOPE_OVERHEAD:
            raise BackupFormatError('Encrypted backup size or format is invalid')
        with source.open('rb') as reader:
            header = reader.read(len(ENVELOPE_MAGIC) + NONCE_SIZE)
            if len(header) != len(ENVELOPE_MAGIC) + NONCE_SIZE or not header.startswith(ENVELOPE_MAGIC):
                raise BackupFormatError('Encrypted backup format is invalid')
            nonce = header[len(ENVELOPE_MAGIC):]
            reader.seek(size - TAG_SIZE)
            tag = reader.read(TAG_SIZE)
            ciphertext_size = size - ENVELOPE_OVERHEAD
            reader.seek(len(ENVELOPE_MAGIC) + NONCE_SIZE)
            decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
            decryptor.authenticate_additional_data(ENVELOPE_MAGIC)
            with target.open('xb') as writer:
                created = True
                target.chmod(0o600)
                remaining = ciphertext_size
                while remaining:
                    chunk = reader.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise BackupFormatError('Encrypted backup is truncated')
                    remaining -= len(chunk)
                    writer.write(decryptor.update(chunk))
                try:
                    writer.write(decryptor.finalize())
                except InvalidTag as exc:
                    raise BackupAuthenticationError('Backup authentication failed; check the encryption key') from exc
                writer.flush()
                os.fsync(writer.fileno())
    except Exception:
        if created: target.unlink(missing_ok=True)
        raise


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        initialize_catalogue(self.root)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.root/'catalogue.sqlite', timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def get(self, key, default=None):
        with self.db() as db: row = db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(key,json.dumps(value)))

    def schedule(self):
        return self.get('schedule', {'enabled':False,'hour':3,'minute':0,'timezone':settings.armory_timezone,'retention':7})

    def path(self, identifier):
        identifier = str(uuid.UUID(str(identifier)))
        return self.root/(identifier+'.armorybackup')

    def records(self):
        with self.db() as db: return [dict(r) for r in db.execute('SELECT * FROM backups ORDER BY created DESC,id DESC')]

    def record(self, identifier):
        with self.db() as db: row=db.execute('SELECT * FROM backups WHERE id=?',(str(identifier),)).fetchone()
        if row is None: raise ValueError('Backup not found')
        return dict(row)

    def jobs(self):
        with self.db() as db: return [dict(r) for r in db.execute('SELECT * FROM jobs ORDER BY created DESC LIMIT 30')]

    def enqueue(self, kind, backup_id=None, next_due=None):
        if kind not in {'manual','automatic','restore'}: raise ValueError('Invalid operation')
        if self.get('maintenance',False): raise Busy('Recovery requires offline attention')
        identifier=str(uuid.uuid4())
        try:
            with self.db() as db:
                db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,NULL)',(identifier,kind,backup_id,'queued','queued',now().isoformat()))
                if next_due is not None:
                    db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('next_run',json.dumps(next_due)))
        except sqlite3.IntegrityError as exc: raise Busy('Another backup/recovery operation is pending') from exc
        return identifier

    def phase(self, identifier, phase, state='running', error=None):
        with self.db() as db: db.execute('UPDATE jobs SET phase=?,state=?,error=? WHERE id=?',(phase,state,error,identifier))

    def reconcile(self):
        # Called only while holding the worker lock; never resets a live worker.
        with self.db() as db:
            for job in db.execute("SELECT id,kind FROM jobs WHERE state='running'").fetchall():
                if job['kind']!='restore':
                    db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('notice:'+job['id'],json.dumps({'callback':'backup_event','args':['backup_failed',job['id']]})))
            db.execute("UPDATE jobs SET state='failed',phase='interrupted',error='Worker interrupted; inspect recovery status' WHERE state='running'")
            for row in db.execute('SELECT id FROM backups').fetchall():
                if not self.path(row['id']).is_file(): db.execute("UPDATE backups SET status='missing' WHERE id=?",(row['id'],))
        known={r['id'] for r in self.records()}
        for path in self.root.glob('*.armorybackup'):
            if path.stem not in known:
                try:
                    manifest=validate_archive(path,self)
                    self.register(path.stem,'imported',manifest)
                except BackupKeyError:
                    # Keep encrypted orphan files untouched until an operator supplies
                    # the correct key; a missing key does not make data invalid.
                    continue
                except BackupAuthenticationError:
                    # Preserve unknown encrypted files; never infer corruption from a
                    # potentially misconfigured key.
                    continue
                except (ValueError, OSError, tarfile.TarError):
                    # Invalid UUID-named orphan archives remain explicitly deletable.
                    try: identifier=str(uuid.UUID(path.stem))
                    except ValueError: continue
                    with self.db() as db:
                        db.execute('INSERT OR IGNORE INTO backups VALUES (?,?,?,?,?,?)',(identifier,'imported',now().isoformat(),'unknown',path.stat().st_size,'invalid'))
        for path in self.root.glob('*.partial'): path.unlink(missing_ok=True)
        for pattern in ('stage-*','restore-*','decrypt-*'):
            for path in self.root.glob(pattern):
                if path.is_dir() and not path.is_symlink(): shutil.rmtree(path)

    def register(self, identifier, kind, manifest):
        if kind not in TYPES: raise ValueError('Invalid backup type')
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO backups VALUES (?,?,?,?,?,?)',
                (identifier,kind,manifest['created_at'],manifest['app_version'],self.path(identifier).stat().st_size,'valid'))


def store():
    return Store(settings.armory_backup_dir)


@contextmanager
def lock(name, exclusive=True, blocking=False, storage=None):
    storage=storage or store()
    descriptor=os.open(storage.root/(name+'.lock'),os.O_CREAT|os.O_RDWR,0o600)
    try:
        try: fcntl.flock(descriptor,(fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)|(0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError as exc: raise Busy('Backup/recovery maintenance in progress') from exc
        yield
    finally:
        os.close(descriptor)


def pg_command(tool, *args):
    env=dict(os.environ,PGPASSWORD=settings.postgres_password,PGCONNECT_TIMEOUT='10')
    command=[tool,'--host',settings.postgres_host,'--port',str(settings.postgres_port),
             '--username',settings.postgres_user,'--dbname',settings.postgres_db,*map(str,args)]
    result=subprocess.run(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=1800)
    if result.returncode: raise RuntimeError(f'{tool} failed; database details withheld')
    return result.stdout


def digest(path):
    with open(path,'rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def schema_check():
    from app.db.session import engine
    with engine.connect() as connection:
        if set(connection.execute(text('SELECT version_num FROM alembic_version')).scalars()) != {SCHEMA}:
            raise ValueError('Database schema does not match this application')
        connection.execute(text('SELECT 1 FROM users LIMIT 1'))


def validate_archive(path, storage=None):
    storage = storage or store()
    key = encryption_key()
    if Path(path).stat().st_size > settings.armory_backup_max_bytes + ENVELOPE_OVERHEAD:
        raise ValueError('Encrypted archive exceeds upload limit')
    with tempfile.TemporaryDirectory(dir=storage.root,prefix='decrypt-') as temp:
        plaintext=Path(temp)/'archive.tar'
        decrypt_archive(path,plaintext,key)
        return validate_plain_archive(plaintext)


def validate_plain_archive(path):
    limit=settings.armory_backup_max_bytes
    if Path(path).stat().st_size>limit: raise ValueError('Archive exceeds upload limit')
    try:
        with tarfile.open(path,'r:') as archive:
            members=[]
            for member in archive:
                members.append(member)
                if len(members)>3: raise ValueError('Too many archive entries')
            if len(members)!=3 or {m.name for m in members}!={'manifest.json','database.dump','schedule.json'}:
                raise ValueError('Archive must contain only manifest, database and schedule')
            if any(not m.isfile() or m.issparse() or m.size<0 or m.size>limit for m in members) or sum(m.size for m in members)>limit:
                raise ValueError('Unsafe archive entries or expanded size')
            if archive.getmember('manifest.json').size>65536 or archive.getmember('schedule.json').size>65536:
                raise ValueError('Oversized archive metadata')
            manifest=json.load(archive.extractfile('manifest.json'))
            if manifest.get('format')!=1 or manifest.get('app_version')!=settings.app_version or manifest.get('schema')!=[SCHEMA]:
                raise ValueError('Unsupported backup version/schema; use the matching application version')
            timestamp=datetime.fromisoformat(manifest['created_at'])
            if timestamp.tzinfo is None: raise ValueError('Archive timestamp must include timezone')
            if set(manifest['inventory'])!={'database.dump','schedule.json'}: raise ValueError('Invalid manifest inventory')
            for name, expected in manifest['inventory'].items():
                with archive.extractfile(name) as stream:
                    actual=hashlib.file_digest(stream,'sha256').hexdigest()
                if actual!=expected['sha256'] or archive.getmember(name).size!=expected['size']:
                    raise ValueError('Archive checksum or size mismatch')
            with archive.extractfile('database.dump') as stream:
                if stream.read(5)!=b'PGDMP': raise ValueError('Not a PostgreSQL custom dump')
            schedule=json.load(archive.extractfile('schedule.json'))
            validate_schedule(schedule)
            return manifest
    except (KeyError,TypeError,json.JSONDecodeError,tarfile.TarError,OverflowError) as exc:
        raise ValueError('Malformed backup archive') from exc


def create_backup(kind, storage=None):
    storage=storage or store()
    if kind not in TYPES-{'imported'}: raise ValueError('Invalid creation type')
    key=encryption_key()
    schema_check()
    identifier=str(uuid.uuid4())
    partial=storage.root/(identifier+'.partial')
    try:
        with tempfile.TemporaryDirectory(dir=storage.root,prefix='stage-') as temp:
            root=Path(temp)
            pg_command('pg_dump','--format=custom','--no-owner','--no-acl','--file',root/'database.dump')
            (root/'schedule.json').write_text(json.dumps(storage.schedule()))
            manifest={'format':1,'app_version':settings.app_version,'schema':[SCHEMA],
                      'created_at':now().isoformat(),'inventory':{}}
            for name in ('database.dump','schedule.json'):
                (root/name).chmod(0o600)
                manifest['inventory'][name]={'size':(root/name).stat().st_size,'sha256':digest(root/name)}
            (root/'manifest.json').write_text(json.dumps(manifest))
            (root/'manifest.json').chmod(0o600)
            plaintext=root/'archive.tar'
            with tarfile.open(plaintext,'w') as archive:
                for name in ('database.dump','schedule.json','manifest.json'): archive.add(root/name,arcname=name,recursive=False)
            plaintext.chmod(0o600)
            encrypt_archive(plaintext,partial,key)
            validate_archive(partial,storage)
            os.replace(partial,storage.path(identifier))
            storage.register(identifier,kind,manifest)
        return identifier
    finally: partial.unlink(missing_ok=True)


def prune(storage):
    retention=storage.schedule()['retention']
    if retention==0: return []
    automatic=[r for r in storage.records() if r['kind']=='automatic' and r['status']=='valid']
    failures=[]
    for row in automatic[retention:]:
        try: delete_backup(row['id'],storage)
        except (OSError, sqlite3.Error, Busy): failures.append(row['id'])
    return failures


def delete_backup(identifier, storage=None):
    storage=storage or store()
    storage.record(identifier)
    with storage.db() as db:
        if db.execute("SELECT 1 FROM jobs WHERE backup_id=? AND state IN ('running','queued')",(str(identifier),)).fetchone():
            raise Busy('Archive is in use')
        storage.path(identifier).unlink(missing_ok=True)
        db.execute('DELETE FROM backups WHERE id=?',(str(identifier),))


def restore_database(path, storage=None):
    from app.db.session import engine
    storage=storage or store()
    key=encryption_key()
    with tempfile.TemporaryDirectory(dir=storage.root,prefix='restore-') as temp:
        plaintext=Path(temp)/'archive.tar'
        decrypt_archive(path,plaintext,key)
        dump=Path(temp)/'database.dump'
        with tarfile.open(plaintext) as archive, dump.open('wb') as stream:
            shutil.copyfileobj(archive.extractfile('database.dump'),stream)
        engine.dispose()
        pg_command('pg_restore','--clean','--if-exists','--no-owner','--no-acl','--single-transaction','--exit-on-error',dump)
        engine.dispose()
    schema_check()


def restore_backup(identifier, storage=None):
    storage=storage or store()
    path=storage.path(identifier)
    validate_archive(path,storage)
    # No mutation unless a verified pre-restore archive has been published.
    before=create_backup('pre-restore',storage)
    storage.put('maintenance',True)
    storage.put('recovery',{'state':'restoring','pre_restore':before,'source':str(identifier)})
    try:
        restore_database(path,storage)
        reconcile_outbox()
        with storage.db() as db: db.execute("DELETE FROM settings WHERE key LIKE 'notice:%'")
        storage.put('recovery',{'state':'restored','pre_restore':before})
    except Exception:
        try:
            restore_database(storage.path(before),storage)
            reconcile_outbox()
            with storage.db() as db: db.execute("DELETE FROM settings WHERE key LIKE 'notice:%'")
            storage.put('recovery',{'state':'rolled_back','pre_restore':before})
        except Exception:
            storage.put('recovery',{'state':'offline_recovery_required','pre_restore':before})
            raise RuntimeError('Recovery failed; maintenance remains enabled. Use the pre-restore archive offline.') from None
        raise RuntimeError('Restore failed; original database recovered from the pre-restore archive.') from None
    finally:
        storage.put('epoch',secrets.token_hex(16))
        schedule=storage.schedule(); schedule['enabled']=False; storage.put('schedule',schedule)
        if storage.get('recovery',{}).get('state') in {'restored','rolled_back'}:
            storage.put('maintenance',False)


def reconcile_outbox():
    from app.db.session import SessionLocal
    with SessionLocal() as db:
        db.execute(text("UPDATE notification_recipients SET email_state='cancelled', diagnostic='Cancelled after recovery' WHERE email_state IN ('pending','retry','sending')"))
        db.commit()


def validate_schedule(value):
    if not isinstance(value,dict) or set(value)!={'enabled','hour','minute','timezone','retention'} or not isinstance(value.get('enabled'),bool): raise ValueError('Invalid schedule')
    for key,maximum in [('hour',23),('minute',59),('retention',100000)]:
        if type(value.get(key)) is not int or not 0<=value[key]<=maximum: raise ValueError('Invalid schedule '+key)
    ZoneInfo(value['timezone'])
    return value


def next_run(schedule, after=None):
    after=after or now(); zone=ZoneInfo(schedule['timezone']); local=after.astimezone(zone)
    for offset in range(3):
        day=local.date()+timedelta(days=offset)
        wall=datetime(day.year,day.month,day.day,schedule['hour'],schedule['minute'],tzinfo=zone,fold=0)
        instant=wall.astimezone(UTC)
        if instant.astimezone(zone).replace(tzinfo=None)!=wall.replace(tzinfo=None): continue
        if instant>after: return instant
    raise ValueError('Unable to compute next backup time')


def safe_notify(callback, *args):
    storage=store()
    key='notice:'+str(args[-1] if args else uuid.uuid4())
    storage.put(key, {'callback':callback.__name__, 'args':args})
    try:
        callback(*args)
    except Exception:
        storage.put('notification_error','Notification persistence pending; backup outcome is unchanged')
    else:
        with storage.db() as db: db.execute('DELETE FROM settings WHERE key=?',(key,))


def flush_notices(storage):
    from app.services.notification_service import backup_event, resolve_cleanup, restore_initiated
    callbacks={'backup_event':backup_event,'resolve_cleanup':resolve_cleanup,
               'restore_initiated':restore_initiated}
    with storage.db() as db: rows=db.execute("SELECT key,value FROM settings WHERE key LIKE 'notice:%' LIMIT 20").fetchall()
    for row in rows:
        value=json.loads(row['value']);callbacks[value['callback']](*value['args'])
        with storage.db() as db: db.execute('DELETE FROM settings WHERE key=?',(row['key'],))
    storage.put('notification_error',None)


def run_job(job, storage):
    storage.phase(job['id'],'starting')
    try:
        with lock('maintenance',storage=storage,blocking=True):
            storage.phase(job['id'],'restoring' if job['kind']=='restore' else 'creating archive')
            if job['kind']=='restore':
                from app.services.notification_service import restore_recipients, utcnow
                storage.put('notice:'+job['id'],{'callback':'restore_initiated','args':[
                    job['id'],restore_recipients(),utcnow().isoformat()]})
                restore_backup(job['backup_id'],storage)
            else:
                identifier=create_backup(job['kind'],storage)
                storage.put('last_success',now().isoformat())
                if job['kind']=='automatic': storage.put('last_automatic',now().isoformat())
                failures=prune(storage) if job['kind']=='automatic' else []
                if job['kind']=='automatic': storage.put('cleanup_failed',bool(failures))
                from app.services.notification_service import backup_event, resolve_cleanup
                if failures:
                    safe_notify(backup_event, 'cleanup_failed',job['id'])
                else:
                    if job['kind']=='automatic': safe_notify(resolve_cleanup)
                    safe_notify(backup_event, 'backup_completed',job['id'])
                storage.put('last_backup_id',identifier)
        storage.phase(job['id'],'completed','completed')
    except Exception as exc:
        # Never persist raw command/SQL/SMTP exceptions or inventory data.
        storage.phase(job['id'],'failed','failed', 'Operation failed; review recovery/health status. '+type(exc).__name__)
        if job['kind']!='restore':
            from app.services.notification_service import backup_event
            try: safe_notify(backup_event, 'backup_failed',job['id'])
            except Exception: storage.put('notification_error','Notification persistence failed; inspect database readiness')


def worker_tick(storage):
    with lock('worker',storage=storage):
        storage.reconcile()
        if storage.get('maintenance',False): return
        schedule=storage.schedule()
        if schedule['enabled']:
            due=storage.get('next_run')
            if due is None: storage.put('next_run',next_run(schedule).isoformat())
            elif datetime.fromisoformat(due)<=now():
                try: storage.enqueue('automatic',next_due=next_run(schedule).isoformat())
                except Busy: pass
        with storage.db() as db: job=db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
        if job: run_job(dict(job),storage)
        if not storage.get('maintenance',False):
            from app.services.notification_service import deliver_pending, retain_history
            from app.services.update_service import check_if_due
            flush_notices(storage)
            check_if_due()
            deliver_pending()
            retain_history()
        with storage.db() as db:
            db.execute("DELETE FROM jobs WHERE state NOT IN ('queued','running') AND created < ?",((now()-timedelta(days=90)).isoformat(),))
        storage.put('worker_heartbeat',now().isoformat())


def health(storage=None):
    storage=storage or store()
    checks={}
    try: schema_check(); checks['database_schema']='ready'
    except Exception: checks['database_schema']='unavailable or migration required'
    try:
        with tempfile.TemporaryFile(dir=storage.root) as stream: stream.write(b'probe'); stream.flush()
        checks['storage']='writable'; checks['free_bytes']=shutil.disk_usage(storage.root).free
    except OSError: checks['storage']='unwritable'
    try: encryption_key(); checks['encryption']='ready'
    except BackupKeyError: checks['encryption']='missing or invalid key'
    checks.update(schedule=storage.schedule(),next_run=storage.get('next_run'),last_success=storage.get('last_success'),
                  last_automatic=storage.get('last_automatic'),worker_heartbeat=storage.get('worker_heartbeat'),
                  maintenance=storage.get('maintenance',False),recovery=storage.get('recovery'),
                  cleanup_failed=storage.get('cleanup_failed',False),notification_error=storage.get('notification_error'))
    heartbeat=checks['worker_heartbeat']
    checks['scheduler_status']='disabled' if not checks['schedule']['enabled'] else ('running' if heartbeat and now()-datetime.fromisoformat(heartbeat)<timedelta(minutes=2) else 'not running')
    checks['status']='healthy' if checks['database_schema']=='ready' and checks.get('storage')=='writable' and checks['encryption']=='ready' and checks['scheduler_status']!='not running' and not checks['maintenance'] else 'degraded'
    return checks
