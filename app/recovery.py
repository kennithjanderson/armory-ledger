"""Offline recovery: stop all application workers before invoking this module."""
import argparse
import os
from pathlib import Path
import shutil
import uuid
from app.services.backup_service import store, lock, validate_archive, restore_backup


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive',type=Path)
    parser.add_argument('--confirm-replace-all-data',action='store_true',required=True)
    args=parser.parse_args()
    storage=store()
    with lock('worker',storage=storage), lock('maintenance',storage=storage):
        manifest=validate_archive(args.archive,storage)
        identifier=str(uuid.uuid4())
        target=storage.path(identifier)
        shutil.copyfile(args.archive,target); target.chmod(0o600)
        storage.register(identifier,'imported',manifest)
        restore_backup(identifier,storage)
    print('Recovery verified. Automatic backups disabled; historical mail cancelled. Sign in again.')


if __name__=='__main__': main()
