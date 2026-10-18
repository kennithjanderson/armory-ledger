"""Admin-only whole-instance operations and recipient-owned notifications."""
import os
from pathlib import Path
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select, text
from app.api.admin import render
from app.core.csrf import require_csrf, csrf_token
from app.core.dependencies import get_current_user, require_admin, get_db
from app.core.config import settings
from app.main_templates import templates
from app.models.notification import NotificationEvent, NotificationRecipient
from app.services import backup_service as backup
from app.services import notification_service as notices

admin=APIRouter(prefix='/admin',dependencies=[Depends(require_admin)])
user_routes=APIRouter(dependencies=[Depends(get_current_user)])


@admin.get('/backups')
def backup_page(request: Request,user=Depends(require_admin)):
    return render(request,user,'admin/backups.html')


@admin.get('/backups/status')
def backup_status():
    storage=backup.store()
    return {'health':backup.health(storage),'backups':storage.records(),'jobs':storage.jobs()}


@admin.get('/operational-status')
def operational_status(db=Depends(get_db)):
    """Return a privacy-safe summary for the administrator footer popover."""
    try:
        db.execute(text('SELECT 1'))
        database='connected'
    except Exception:
        database='unavailable'

    checks=backup.health()
    recovery=checks.get('recovery') or {}
    recovery_state=recovery.get('state') if isinstance(recovery,dict) else None
    if recovery_state=='offline_recovery_required':
        recovery_status='offline recovery required'
    elif recovery_state=='restoring':
        recovery_status='restore in progress'
    elif recovery_state:
        recovery_status='last recovery: '+str(recovery_state)
    else:
        recovery_status='none recorded'

    mail=notices.mail_config(db,public=True)
    if not mail['enabled']:
        email_status='disabled'
    elif not mail['host'] or not mail['from_address']:
        email_status='needs configuration'
    elif mail['password_set'] and not mail['key_configured']:
        email_status='SMTP encryption key unavailable'
    else:
        email_status='enabled; live delivery not tested'

    return {
        'database':database,
        'backups':{
            'status':checks['status'],
            'storage':checks['storage'],
            'encryption':checks['encryption'],
            'scheduler':checks['scheduler_status'],
            'maintenance':'active' if checks['maintenance'] else 'clear',
            'recovery':recovery_status,
        },
        'email':email_status,
    }


@admin.put('/backups/schedule',dependencies=[Depends(require_csrf)])
def schedule(payload: dict):
    try:
        value=backup.validate_schedule(payload)
        with backup.lock('worker'):
            storage=backup.store(); storage.put('schedule',value)
            storage.put('next_run',backup.next_run(value).isoformat() if value['enabled'] else None)
        return {'success':True}
    except (ValueError,KeyError) as exc: raise HTTPException(422,'Invalid schedule, timezone or retention') from exc
    except backup.Busy as exc: raise HTTPException(409,str(exc)) from exc


@admin.post('/backups',dependencies=[Depends(require_csrf)],status_code=202)
def backup_now():
    try: return {'job_id':backup.store().enqueue('manual')}
    except backup.Busy as exc: raise HTTPException(409,str(exc)) from exc


@admin.post('/backups/import',dependencies=[Depends(require_csrf)],status_code=201)
async def import_backup(request: Request):
    storage=backup.store(); identifier=str(uuid.uuid4()); temporary=storage.root/(identifier+'.partial')
    try:
        with backup.lock('worker',storage=storage):
            count=0
            with temporary.open('xb') as output:
                temporary.chmod(0o600)
                async for chunk in request.stream():
                    count+=len(chunk)
                    if count>settings.armory_backup_max_bytes+backup.ENVELOPE_OVERHEAD: raise HTTPException(413,'Archive too large')
                    output.write(chunk)
            manifest=backup.validate_archive(temporary,storage)
            os.replace(temporary,storage.path(identifier)); storage.register(identifier,'imported',manifest)
        return {'id':identifier}
    except backup.Busy as exc: raise HTTPException(409,str(exc)) from exc
    except (ValueError,OSError) as exc: raise HTTPException(422,'Invalid archive or unavailable backup storage') from exc
    finally: temporary.unlink(missing_ok=True)


@admin.get('/backups/{identifier}/download')
def download(identifier: uuid.UUID):
    storage=backup.store()
    try:
        record=storage.record(identifier); path=storage.path(identifier)
        if record['status']!='valid' or not path.is_file(): raise ValueError('Backup unavailable')
        # Open descriptor remains valid even if a later explicit deletion unlinks it.
        from fastapi.responses import StreamingResponse
        def chunks():
            with backup.lock('worker',storage=storage), path.open('rb') as stream:
                while chunk:=stream.read(1024*1024): yield chunk
        return StreamingResponse(chunks(),media_type='application/octet-stream',headers={'Content-Disposition':f'attachment; filename="armory-{identifier}.armorybackup"','Cache-Control':'no-store'})
    except ValueError as exc: raise HTTPException(404,str(exc)) from exc


@admin.delete('/backups/{identifier}',dependencies=[Depends(require_csrf)])
def delete(identifier: uuid.UUID,payload: dict):
    if payload.get('confirmation')!='DELETE': raise HTTPException(422,'Type DELETE to confirm')
    try:
        with backup.lock('worker'): backup.delete_backup(identifier)
        return {'success':True}
    except backup.Busy as exc: raise HTTPException(409,str(exc)) from exc
    except (ValueError,OSError) as exc: raise HTTPException(409,'Deletion failed; archive retained if present') from exc


@admin.post('/backups/{identifier}/restore',dependencies=[Depends(require_csrf)],status_code=202)
def restore(identifier: uuid.UUID,payload: dict):
    if payload.get('confirmation')!='REPLACE ALL DATA': raise HTTPException(422,'Type REPLACE ALL DATA to confirm')
    try:
        storage=backup.store()
        with backup.lock('worker',storage=storage):
            backup.validate_archive(storage.path(identifier),storage)
            return {'job_id':storage.enqueue('restore',str(identifier))}
    except backup.Busy as exc: raise HTTPException(409,str(exc)) from exc
    except (ValueError,OSError) as exc: raise HTTPException(422,'Invalid or incompatible backup') from exc


@admin.get('/email')
def email_page(request: Request,user=Depends(require_admin)):
    return render(request,user,'admin/email.html')


@admin.get('/email/settings')
def email_settings(db=Depends(get_db)):
    rows=db.execute(select(NotificationRecipient,NotificationEvent).join(NotificationEvent).where(
        NotificationRecipient.email_state!='disabled').order_by(NotificationRecipient.next_attempt.desc()).limit(40)).all()
    return {'settings':notices.mail_config(db,public=True),'deliveries':[{'id':str(r.id),'title':e.title,
        'state':r.email_state,'attempts':r.attempts,'diagnostic':r.diagnostic,'next_attempt':r.next_attempt.isoformat()} for r,e in rows]}


@admin.put('/email/settings',dependencies=[Depends(require_csrf)])
def save_email(payload: dict,db=Depends(get_db)):
    try: notices.save_mail(db,payload); return {'success':True}
    except (ValueError,TypeError) as exc: raise HTTPException(422,str(exc)) from exc


@admin.post('/email/test',dependencies=[Depends(require_csrf)],status_code=202)
def test_email(payload: dict,user=Depends(require_admin),db=Depends(get_db)):
    if payload.get('confirmation')!='SEND TEST': raise HTTPException(422,'Confirm the test recipient with SEND TEST')
    try: return {'delivery_id':notices.test_email(db,user,payload.get('recipient'))}
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc


@user_routes.get('/notifications')
def notifications(request: Request,user=Depends(get_current_user)):
    return templates.TemplateResponse(request=request,name='notifications.html',context={
        'app_name':settings.app_name,'app_version':settings.app_version,'current_user':user,'is_admin':user.is_admin,'csrf_token':csrf_token(request)})


@user_routes.get('/settings')
def settings_page(request: Request,user=Depends(get_current_user)):
    return templates.TemplateResponse(request=request,name='settings.html',context={
        'app_name':settings.app_name,'app_version':settings.app_version,'current_user':user,
        'is_admin':user.is_admin,'csrf_token':csrf_token(request)})


@user_routes.get('/api/notifications')
def list_notices(request: Request,offset: int=0,unread_only: bool=False,user=Depends(get_current_user),db=Depends(get_db)):
    if not 0<=offset<=100000: raise HTTPException(422,'Invalid page offset')
    preferences={'success_in_app':user.backup_success_in_app,'success_email':user.backup_success_email}
    if user.is_admin:
        preferences.update(restore_initiated_in_app=user.restore_initiated_in_app,
                           restore_initiated_email=user.restore_initiated_email)
    return {**notices.notices(db,user,offset,unread_only=unread_only),'csrf_token':csrf_token(request),
            'preferences':preferences}


@user_routes.post('/api/notifications/read',dependencies=[Depends(require_csrf)])
def read_notices(payload: dict,user=Depends(get_current_user),db=Depends(get_db)):
    try:
        notices.mark_read(db,user,uuid.UUID(payload['id']) if payload.get('id') else None)
        return {'success':True}
    except ValueError as exc: raise HTTPException(404,'Notice not found') from exc


@user_routes.put('/api/notifications/preferences',dependencies=[Depends(require_csrf)])
def preferences(payload: dict,user=Depends(get_current_user),db=Depends(get_db)):
    basic={'success_in_app','success_email'}
    restore={'restore_initiated_in_app','restore_initiated_email'}
    allowed=(basic,basic|restore) if user.is_admin else (basic,)
    if not any(set(payload)==keys for keys in allowed) or any(type(v) is not bool for v in payload.values()):
        raise HTTPException(422,'Expected success preferences as booleans')
    user.backup_success_in_app=payload['success_in_app']; user.backup_success_email=payload['success_email']
    if user.is_admin and restore.issubset(payload):
        user.restore_initiated_in_app=payload['restore_initiated_in_app']
        user.restore_initiated_email=payload['restore_initiated_email']
    db.commit()
    return {'success':True}
