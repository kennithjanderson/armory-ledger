"""Small persistent-job worker; no broker, cron or additional service required."""
from contextlib import asynccontextmanager
import logging
import threading
from app.core.config import settings
from app.services.backup_service import Busy, store, worker_tick


@asynccontextmanager
async def lifespan(app):
    stop=threading.Event()
    def work():
        while not stop.is_set():
            try: worker_tick(store())
            except Busy: pass
            except Exception:
                logging.getLogger(__name__).error('Background operation failed; details withheld. Check admin health.')
            stop.wait(5)
    thread=None
    if settings.armory_worker_enabled:
        thread=threading.Thread(target=work,name='armory-operations',daemon=True); thread.start()
    yield
    stop.set()
    if thread: thread.join(timeout=35)
