"""Shared volume locks coordinate requests with snapshot/recovery across workers."""
from fastapi.responses import JSONResponse
from app.services.backup_service import Busy, lock, store


class MaintenanceMiddleware:
    def __init__(self, app): self.app=app

    async def __call__(self, scope, receive, send):
        if scope['type']!='http' or scope.get('path','').startswith('/static'):
            return await self.app(scope,receive,send)
        storage=store()
        # During a snapshot this read-only status endpoint may report progress.
        if scope.get('path') == '/admin/backups/status' and scope.get('method') == 'GET' and not storage.get('maintenance',False):
            return await self.app(scope,receive,send)
        if storage.get('maintenance',False):
            return await JSONResponse({'detail':'Recovery maintenance; try again later'},status_code=503)(scope,receive,send)
        try:
            with lock('maintenance',exclusive=False,storage=storage):
                await self.app(scope,receive,send)
        except Busy:
            await JSONResponse({'detail':'Backup/recovery in progress; retry shortly'},status_code=503)(scope,receive,send)
