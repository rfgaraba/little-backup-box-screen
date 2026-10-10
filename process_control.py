"""Stop only the process group created for this backup job."""
import os
import signal
import time


def group_alive(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


def stop_group(process):
    pgid = process.pid
    if pgid <= 1:
        raise ValueError('Grupo de procesos inválido')
    if not group_alive(pgid):
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 10
    while group_alive(pgid) and time.monotonic() < deadline:
        process.poll()  # Reap the leader while waiting for its children to stop.
        time.sleep(.1)
    if group_alive(pgid):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + 3
        while group_alive(pgid) and time.monotonic() < deadline:
            process.poll()
            time.sleep(.1)
    if group_alive(pgid):
        raise ValueError('No se pudo confirmar la detención de todos los procesos')
