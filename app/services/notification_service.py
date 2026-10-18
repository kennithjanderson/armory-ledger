"""Reusable persistent events and independent in-app/email delivery channels."""
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.headerregistry import Address
import html
import re
import smtplib
import ssl
import uuid
from urllib.parse import urlparse
from cryptography.fernet import Fernet
from sqlalchemy import delete, func, select
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.notification import NotificationEvent, NotificationRecipient, SystemSetting
from app.models.user import User

EVENTS={
    'backup_failed':('error','Backup failed','Backup could not be completed. Review Backup & Recovery.'),
    'backup_completed':('success','Backup completed','A new backup is ready in Backup & Recovery.'),
    'cleanup_failed':('warning','Backup cleanup failed','Backup completed, but older automatic backups could not be removed.'),
}
DEFAULT_MAIL={'enabled':False,'host':'','port':587,'security':'starttls','username':'','password_encrypted':'',
              'timeout':10,'from_name':'Armory Ledger','from_address':'','reply_to':'','base_url':''}
UPSTREAM_RELEASE_URL='https://github.com/kennithjanderson/armory-ledger/releases/tag/v'


def utcnow(): return datetime.now(timezone.utc)


def mailbox(value):
    if not isinstance(value,str) or not re.fullmatch(r"[A-Za-z0-9.!$%&'*+/=_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",value):
        raise ValueError('Enter a plain email address')
    return value


def mail_config(db, public=False):
    row=db.get(SystemSetting,'email')
    config={**DEFAULT_MAIL,**(row.value if row else {})}
    if public:
        config['password_set']=bool(config.pop('password_encrypted'))
        config['key_configured']=bool(settings.armory_secret_key)
    return config


def save_mail(db, payload):
    allowed=set(DEFAULT_MAIL)-{'password_encrypted'}|{'password','clear_password'}
    if set(payload)-allowed: raise ValueError('Unknown email setting')
    if 'password' in payload and (not isinstance(payload['password'],str) or len(payload['password'])>4096): raise ValueError('Invalid password value')
    if 'clear_password' in payload and type(payload['clear_password']) is not bool: raise ValueError('Clear password must be a boolean')
    if payload.get('clear_password') and payload.get('password'): raise ValueError('Choose replacement or clear, not both')
    old=mail_config(db); config={**old,**{k:v for k,v in payload.items() if k in DEFAULT_MAIL}}
    if type(config['enabled']) is not bool: raise ValueError('Invalid enabled state')
    if type(config['port']) is not int or not 1<=config['port']<=65535: raise ValueError('Invalid SMTP port')
    if type(config['timeout']) is not int or not 1<=config['timeout']<=30: raise ValueError('Timeout must be 1–30 seconds')
    if config['security'] not in ('starttls','tls','plain'): raise ValueError('Choose explicit SMTP transport security')
    for key in ('host','username','from_name','from_address','reply_to','base_url'):
        if not isinstance(config[key],str) or len(config[key])>500 or any(ord(c)<32 for c in config[key]):
            raise ValueError('Invalid email configuration text')
    if config['enabled']:
        mailbox(config['from_address'])
        if not config['host'] or not re.fullmatch(r'[A-Za-z0-9.:-]+',config['host']): raise ValueError('Invalid SMTP host')
        if config['reply_to']: mailbox(config['reply_to'])
        parsed=urlparse(config['base_url'])
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
            raise ValueError('Public base URL must be an HTTP(S) origin without credentials, query or path')
    if payload.get('clear_password'):
        config['password_encrypted']=''
    if payload.get('password'):
        if not settings.armory_secret_key: raise ValueError('Configure ARMORY_SECRET_KEY before storing an SMTP password')
        if len(payload['password'])>4096: raise ValueError('Password too long')
        config['password_encrypted']=Fernet(settings.armory_secret_key.encode()).encrypt(payload['password'].encode()).decode()
    if config['enabled'] and config['password_encrypted'] and not config['username']: raise ValueError('SMTP password requires username')
    if config['enabled'] and config['password_encrypted']:
        try: Fernet((settings.armory_secret_key or '').encode()).decrypt(config['password_encrypted'].encode())
        except Exception: raise ValueError('SMTP encryption key unavailable or incorrect') from None
    row=db.get(SystemSetting,'email')
    if row: row.value=config
    else: db.add(SystemSetting(key='email',value=config))
    if not config['enabled']:
        for delivery in db.scalars(select(NotificationRecipient).where(NotificationRecipient.email_state.in_(['pending','retry']))):
            delivery.email_state='disabled'; delivery.diagnostic='Mail disabled; not replayed when enabled'
    db.commit()


def backup_event(kind, key):
    severity,title,message=EVENTS[kind]
    with SessionLocal() as db:
        if db.scalar(select(NotificationEvent).where(NotificationEvent.event_key==key)) or db.get(SystemSetting,'event:'+key): return
        if kind=='backup_completed':
            for previous in db.scalars(select(NotificationEvent).where(
                NotificationEvent.kind=='backup_failed',NotificationEvent.resolved.is_(False))):
                previous.resolved=True; previous.updated_at=utcnow()
        event=None
        if kind=='cleanup_failed':
            event=db.scalar(select(NotificationEvent).where(NotificationEvent.kind==kind,NotificationEvent.resolved.is_(False)))
        repeated=event is not None
        if event:
            event.occurrences+=1; event.updated_at=utcnow()
        else:
            event=NotificationEvent(event_key=key,kind=kind,severity=severity,title=title,message=message,updated_at=utcnow())
            db.add(event); db.flush()
        config=mail_config(db)
        for user in db.scalars(select(User).where(User.is_admin.is_(True))):
            in_app=kind!='backup_completed' or user.backup_success_in_app
            email=kind!='backup_completed' or user.backup_success_email
            recipient=db.scalar(select(NotificationRecipient).where(NotificationRecipient.event_id==event.id,NotificationRecipient.user_id==user.id))
            if not recipient:
                recipient=NotificationRecipient(event_id=event.id,user_id=user.id,in_app=in_app,
                    email_state='pending' if email and config['enabled'] else 'disabled')
                if email and config['enabled'] and not user.email:
                    recipient.email_state='failed'; recipient.diagnostic='Account has no email; update identity-provider claims'
                db.add(recipient)
            elif repeated:
                recipient.read_at=None; recipient.in_app=in_app
                # One email per incident; a resolved incident may alert again.
        # Remember subsequent occurrences for idempotent retries without another notice.
        if repeated:
            db.add(SystemSetting(key='event:'+key,value={'incident':str(event.id),'created':utcnow().isoformat()}))
        db.commit()


def restore_recipients():
    """Snapshot opt-in admin recipients before PostgreSQL is replaced."""
    with SessionLocal() as db:
        users=db.scalars(select(User).where(User.is_admin.is_(True))).all()
        return [{'user_id':str(user.id),'in_app':user.restore_initiated_in_app,
                 'email':user.restore_initiated_email}
                for user in users if user.restore_initiated_in_app or user.restore_initiated_email]


def restore_initiated(job_id, recipients, started_at):
    """Persist a queued pre-restore notice into the post-restore database."""
    if not recipients: return
    timestamp=datetime.fromisoformat(started_at)
    if timestamp.tzinfo is None: raise ValueError('Restore notification timestamp must include a timezone')
    with SessionLocal() as db:
        event_key='restore:'+str(job_id)
        if db.scalar(select(NotificationEvent).where(NotificationEvent.event_key==event_key)): return
        eligible=[]
        for selection in recipients:
            user=db.get(User,uuid.UUID(selection['user_id']))
            if user is not None and user.is_admin and (selection['in_app'] or selection['email']):
                eligible.append((user,selection))
        if not eligible: return
        event=NotificationEvent(event_key=event_key,kind='restore_initiated',scope='admin',severity='warning',
            title='Database restore initiated',
            message='A whole-instance database restore was initiated. Review Backup & Recovery for final operation status.',
            action='/admin/backups',resolved=True,created_at=timestamp,updated_at=timestamp)
        db.add(event); db.flush()
        mail_enabled=mail_config(db)['enabled']
        for user,selection in eligible:
            email_state='disabled'
            diagnostic=None
            if selection['email']:
                if not mail_enabled: diagnostic='System email is not enabled after recovery'
                elif not user.email:
                    email_state='failed'; diagnostic='Account has no email; update identity-provider claims'
                else: email_state='pending'
            db.add(NotificationRecipient(event_id=event.id,user_id=user.id,in_app=selection['in_app'],
                email_state=email_state,diagnostic=diagnostic))
        db.commit()


def update_available(version, timestamp=None):
    """Create one admin-scoped notice for a newer image, resolving stale notices."""
    timestamp = timestamp or utcnow()
    release_version = version.removeprefix('v') if version else None
    with SessionLocal() as db:
        active = db.scalars(select(NotificationEvent).where(
            NotificationEvent.kind == 'update_available',
            NotificationEvent.resolved.is_(False),
        )).all()
        current_event = None
        if release_version:
            event_key = f'update-available:{release_version}'
            current_event = db.scalar(select(NotificationEvent).where(
                NotificationEvent.event_key == event_key))
        reactivated = False
        for event in active:
            if event is current_event:
                continue
            event.resolved = True
            event.updated_at = timestamp
            for recipient in db.scalars(select(NotificationRecipient).where(
                    NotificationRecipient.event_id == event.id)):
                recipient.read_at = recipient.read_at or timestamp
                if recipient.email_state in ('pending', 'retry'):
                    recipient.email_state = 'cancelled'
                    recipient.diagnostic = 'A newer image tag replaced this update notice'
        if not release_version:
            db.commit()
            return
        mail_enabled = mail_config(db)['enabled']
        if current_event is None:
            current_event = NotificationEvent(
                event_key=f'update-available:{release_version}', kind='update_available', scope='admin',
                severity='info', title=f'Armory Ledger {release_version} is available',
                message=(f'The GHCR latest image is {release_version}; this installation is running '
                         f'{settings.app_version}. Review the release notes before updating.'),
                action=f'{UPSTREAM_RELEASE_URL}{release_version}',
                updated_at=timestamp,
            )
            db.add(current_event)
            db.flush()
        elif current_event.resolved:
            current_event.resolved = False
            current_event.updated_at = timestamp
            current_event.occurrences += 1
            reactivated = True
        for user in db.scalars(select(User).where(User.is_admin.is_(True))):
            recipient = db.scalar(select(NotificationRecipient).where(
                NotificationRecipient.event_id == current_event.id,
                NotificationRecipient.user_id == user.id,
            ))
            if recipient is None:
                email_state = 'pending' if mail_enabled and user.email else 'disabled'
                db.add(NotificationRecipient(
                    event_id=current_event.id, user_id=user.id, in_app=True,
                    email_state=email_state,
                    diagnostic=('Account has no email; update identity-provider claims'
                                if mail_enabled and not user.email else None),
                ))
            elif reactivated:
                recipient.read_at = None
                recipient.in_app = True
                recipient.email_state = 'pending' if mail_enabled and user.email else 'disabled'
                recipient.diagnostic = None
        db.commit()


def resolve_cleanup():
    with SessionLocal() as db:
        for event in db.scalars(select(NotificationEvent).where(NotificationEvent.kind=='cleanup_failed',NotificationEvent.resolved.is_(False))):
            event.resolved=True; event.updated_at=utcnow()
        db.commit()


def visible_query(user):
    query=select(NotificationRecipient,NotificationEvent).join(NotificationEvent).where(
        NotificationRecipient.user_id==user.id,NotificationRecipient.in_app.is_(True))
    if not user.is_admin: query=query.where(NotificationEvent.scope!='admin')
    return query


def notices(db,user,offset=0,unread_only=False):
    query=visible_query(user)
    if unread_only: query=query.where(NotificationRecipient.read_at.is_(None))
    rows=db.execute(query.order_by(NotificationEvent.updated_at.desc(),NotificationEvent.id).offset(offset).limit(30)).all()
    unread=db.scalar(select(func.count()).select_from(visible_query(user).where(NotificationRecipient.read_at.is_(None)).subquery())) or 0
    return {'unread':unread,'items':[{'id':str(r.id),'severity':e.severity,'title':e.title,'message':e.message,
        'timestamp':e.updated_at.isoformat(),'read':r.read_at is not None,'action':e.action,
        'occurrences':e.occurrences,'resolved':e.resolved} for r,e in rows]}


def mark_read(db,user,identifier=None):
    query=visible_query(user)
    if identifier: query=query.where(NotificationRecipient.id==identifier)
    rows=db.execute(query).all()
    if identifier and not rows: raise ValueError('Notice not found')
    for recipient,event in rows: recipient.read_at=utcnow()
    db.commit()


def test_email(db,user,recipient):
    mailbox(recipient)
    if not mail_config(db)['enabled']: raise ValueError('Enable and configure system email first')
    event=NotificationEvent(event_key='test:'+str(uuid.uuid4()),kind='test_email',scope='admin',severity='info',
        title='Armory Ledger test email',message='System email test requested by an administrator.',action='/admin/email')
    db.add(event); db.flush()
    row=NotificationRecipient(event_id=event.id,user_id=user.id,in_app=False,email_state='pending',test_recipient=recipient)
    db.add(row); db.commit()
    return str(row.id)


def message_for(event,delivery,user,config):
    address=delivery.test_recipient if event.kind=='test_email' else user.email
    mailbox(address); mailbox(config['from_address'])
    link=config['base_url'].rstrip('/')+event.action
    updated=event.updated_at
    updated=updated.replace(tzinfo=timezone.utc) if updated.tzinfo is None else updated.astimezone(timezone.utc)
    timestamp=updated.strftime('%Y-%m-%d %H:%M:%S UTC')
    severity=event.severity if event.severity in ('error','warning','success','info') else 'info'
    colors={'error':'#84383d','warning':'#8a5a12','success':'#25633b','info':'#354a66'}
    message=EmailMessage()
    message['Subject']=f'[{severity.upper()}] {event.title}'
    message['From']=Address(display_name=config['from_name'],addr_spec=config['from_address'])
    message['To']=address
    if config['reply_to']: message['Reply-To']=mailbox(config['reply_to'])
    message['Message-ID']=f'<{delivery.id}@armory-ledger.invalid>'
    body=(f'ARMORY LEDGER — {severity.upper()} NOTIFICATION\n\n{event.title}\n\n{event.message}\n\n'
          f'Time: {timestamp}\n\nOpen Armory Ledger: {link}\n')
    message.set_content(body)
    safe_title=html.escape(event.title)
    safe_message=html.escape(event.message).replace('\n','<br>')
    safe_link=html.escape(link,quote=True)
    html_body=f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background-color:#e8e3d8;color:#25292b;font-family:Arial,Helvetica,sans-serif;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{safe_title} — Armory Ledger notification</div>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color:#e8e3d8;">
<tr><td align="center" style="padding:28px 12px;">
<table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0" style="width:100%;max-width:600px;background-color:#f1ede3;border:1px solid #c7c0b2;">
<tr><td style="padding:24px 28px;background-color:#1c304d;color:#ffffff;">
<div style="font-size:20px;font-weight:700;letter-spacing:2px;">ARMORY LEDGER</div>
<div style="margin-top:5px;font-size:11px;letter-spacing:1.5px;color:#e8e3d8;">SELF-HOSTED INVENTORY</div>
</td></tr>
<tr><td style="padding:0;"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"><tr>
<td width="16%" height="5" style="background-color:#84383d;font-size:0;line-height:0;">&nbsp;</td>
<td width="17%" height="5" style="background-color:#f1ede3;font-size:0;line-height:0;">&nbsp;</td>
<td width="67%" height="5" style="background-color:#1c304d;font-size:0;line-height:0;">&nbsp;</td>
</tr></table></td></tr>
<tr><td style="padding:30px 28px 26px;">
<div style="display:inline-block;margin-bottom:14px;padding:5px 9px;border-radius:3px;background-color:{colors[severity]};color:#ffffff;font-size:11px;font-weight:700;letter-spacing:1px;">{severity.upper()} NOTIFICATION</div>
<h1 style="margin:0 0 16px;color:#1c304d;font-size:24px;line-height:1.3;">{safe_title}</h1>
<p style="margin:0 0 20px;padding-left:14px;border-left:3px solid #354a66;font-size:16px;line-height:1.6;">{safe_message}</p>
<p style="margin:0 0 22px;color:#64686a;font-size:13px;">{timestamp}</p>
<a href="{safe_link}" style="display:inline-block;padding:12px 18px;background-color:#1c304d;color:#ffffff;text-decoration:none;font-size:14px;font-weight:700;">Open Armory Ledger</a>
<p style="margin:22px 0 0;color:#64686a;font-size:12px;line-height:1.5;">If the button does not work, copy this address into your browser:<br><a href="{safe_link}" style="color:#354a66;overflow-wrap:anywhere;">{html.escape(link)}</a></p>
</td></tr>
<tr><td style="padding:16px 28px;border-top:1px solid #c7c0b2;color:#64686a;font-size:11px;line-height:1.5;">Automated message from your Armory Ledger installation.</td></tr>
</table></td></tr></table></body></html>'''
    message.add_alternative(html_body,subtype='html')
    return message


def deliver_pending():
    # Worker POSIX lock serializes this claim/send/commit path across processes.
    with SessionLocal() as db:
        config=mail_config(db)
        pending=db.scalars(select(NotificationRecipient).where(NotificationRecipient.email_state.in_(['pending','retry','sending']),
            NotificationRecipient.next_attempt<=utcnow()).order_by(NotificationRecipient.next_attempt).limit(10)).all()
        for delivery in pending:
            user=db.get(User,delivery.user_id); event=db.get(NotificationEvent,delivery.event_id)
            if not user or (event.scope=='admin' and not user.is_admin):
                delivery.email_state='cancelled'; delivery.diagnostic='Recipient no longer authorized'; db.commit(); continue
            if not config['enabled']:
                delivery.email_state='disabled'; delivery.diagnostic='Email disabled'; db.commit(); continue
            delivery.attempts+=1; delivery.email_state='sending'; db.commit()
            try:
                message=message_for(event,delivery,user,config)
                transport=smtplib.SMTP_SSL if config['security']=='tls' else smtplib.SMTP
                options={'timeout':config['timeout']}
                if config['security']=='tls': options['context']=ssl.create_default_context()
                with transport(config['host'],config['port'],**options) as smtp:
                    if config['security']=='starttls': smtp.starttls(context=ssl.create_default_context())
                    if config['username']:
                        password=Fernet((settings.armory_secret_key or '').encode()).decrypt(config['password_encrypted'].encode()).decode() if config['password_encrypted'] else ''
                        smtp.login(config['username'],password)
                    # Refresh authorization immediately before submitting.
                    db.refresh(user)
                    if event.scope=='admin' and not user.is_admin: raise PermissionError('Recipient no longer authorized')
                    smtp.send_message(message)
                delivery.email_state='sent'; delivery.sent_at=utcnow(); delivery.diagnostic='SMTP accepted; inbox delivery is not guaranteed'
            except Exception as exc:
                permanent=isinstance(exc,(ValueError,PermissionError,ssl.SSLError,smtplib.SMTPAuthenticationError,smtplib.SMTPRecipientsRefused)) or (isinstance(exc,smtplib.SMTPResponseException) and exc.smtp_code>=500)
                delivery.email_state='failed' if permanent or delivery.attempts>=3 else 'retry'
                delivery.next_attempt=utcnow()+timedelta(minutes=2**delivery.attempts)
                delivery.diagnostic='SMTP delivery failed: '+type(exc).__name__
            db.commit()


def retain_history():
    current=utcnow()
    retention_days={'error':90,'warning':30,'info':7,'success':7}
    with SessionLocal() as db:
        candidates=db.scalars(select(NotificationEvent).where(
            NotificationEvent.updated_at<current-timedelta(days=7)
        ).order_by(NotificationEvent.updated_at).limit(500)).all()
        for event in candidates:
            retention=retention_days.get(event.severity,7)
            updated=event.updated_at.replace(tzinfo=timezone.utc) if event.updated_at.tzinfo is None else event.updated_at
            if updated>current-timedelta(days=retention): continue
            if event.severity in ('error','warning') and not event.resolved: continue
            recipients=db.scalars(select(NotificationRecipient).where(NotificationRecipient.event_id==event.id)).all()
            if any(r.email_state in ('pending','retry','sending') for r in recipients): continue
            for recipient in recipients: db.delete(recipient)
            db.delete(event)
        for marker in db.scalars(select(SystemSetting).where(SystemSetting.key.like('event:%')).limit(500)):
            stamp=marker.value.get('created')
            if stamp and datetime.fromisoformat(stamp)<cutoff: db.delete(marker)
        db.commit()
