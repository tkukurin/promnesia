#!/usr/bin/env python3

from datetime import datetime
import logging
import os
from os.path import expanduser, join, getsize, lexists
from tempfile import TemporaryDirectory

__logger: logging.Logger = None

def get_logger():
    global __logger
    if __logger is None:
        logging.basicConfig(level=logging.INFO)
        __logger = logging.getLogger("WereYouHere")
    return __logger


def atomic_copy(src: str, dest: str):
    """
    Supposed to handle cases where the file is changed while we were copying it.
    """
    import shutil
    import filecmp

    differs = True
    while differs:
        res = shutil.copy(src, dest)
        differs = not filecmp.cmp(src, res)

def backup_to(prefix: str) -> str:
    today = datetime.now().strftime("%Y%m%d")
    BPATH = f"{prefix}/{today}/"

    os.makedirs(BPATH, exist_ok=True)

    DB = expanduser("~/.config/google-chrome/Default/History")

    # TODO do we need journal?
    # ~/.config/google-chrome/Default/History-journal

    # if your chrome is open, database would normally be locked, so you can't just make a snapshot
    # so we'll just copy it till it converge. bit paranoid, but should work
    atomic_copy(DB, BPATH)
    return join(BPATH, "History")

def merge(merged: str, chunk: str):
    logger = get_logger()
    from subprocess import check_call
    # TODO script relative to path
    if lexists(merged):
        logger.info(f"Merged DB size before: {getsize(merged)}")
    else:
        logger.info(f"Merged DB doesn't exist yet: {merged}")
    check_call(['/L/coding/were-you-here/scripts/merge-chrome-db/merge.sh', merged, chunk])
    logger.info(f"Merged DB size after: {getsize(merged)}")


def update_backup(merged: str):
    with TemporaryDirectory() as tdir: # TODO will it get cleaned up??
        last = backup_to(tdir)
        merge(merged, last)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Backup tool for chrome history db")
    parser.add_argument('merged', type=str, help="Database containin gmerged visits. Should be same as CHROME_HISTORY_DB in config.py")
    args = parser.parse_args()
    update_backup(args.merged)

if __name__ == '__main__':
    main()
