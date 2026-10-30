"""Advisory file locks shared by the Studio editions on each host platform."""
import os
import time
if os.name != 'nt':
    from fcntl import flock, LOCK_EX, LOCK_SH, LOCK_NB, LOCK_UN
else:
    import msvcrt
    LOCK_SH, LOCK_EX, LOCK_NB, LOCK_UN = 1, 2, 4, 8
    def flock(file, operation):
        fd = file if isinstance(file, int) else file.fileno()
        position = os.lseek(fd, 0, os.SEEK_CUR)
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            if operation & LOCK_UN:
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                return
            while True:
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    return
                except OSError as error:
                    if operation & LOCK_NB:
                        raise BlockingIOError('Another Studio operation holds this lock') from error
                    time.sleep(.05)
        finally:
            os.lseek(fd, position, os.SEEK_SET)
