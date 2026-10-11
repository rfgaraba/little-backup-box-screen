"""Read-only backup progress and destination disk I/O sampling."""
from pathlib import Path
import re
import time


def parse_progress(text):
    lines = [re.sub(r'^s=[^:]*:', '', line).strip() for line in text.splitlines()]
    percent = re.search(r'PGBAR=(\d+(?:\.\d+)?)', text)
    counts = next((re.search(r'^(\d+)\s+(?:of|de)\s+(\d+)(\+)?(?:,|$)', line, re.I)
                   for line in lines if re.match(r'^\d+\s+(?:of|de)\s+\d+', line, re.I)), None)
    if not percent and not counts:
        return None
    result = {'progress': min(100, float(percent[1])) if percent else None,
              'phase': 'Procesando archivos', 'eta': None}
    if counts:
        result.update(files_processed=int(counts[1]), files_total=int(counts[2]))
        if int(counts[2]) == 0:
            result['progress'] = None
            result['phase'] = 'Verificando respaldo'
        # A '+' means the engine does not yet know the full file count.
        if counts[3]:
            result['progress'] = None
        elif not percent and int(counts[2]):
            result['progress'] = min(100, int(counts[1]) * 100 / int(counts[2]))
    for line in lines:
        eta = re.search(r':\s*(\d+:\d{2}:\d{2})\s*$', line)
        if eta:
            result['eta'] = eta[1]
    return result


class BackupTelemetry:
    def __init__(self, engine_dir, disk=None, log_offset=0, clock=time.monotonic):
        self.root = Path(engine_dir) / 'tmp'
        self.disk = disk if disk and re.fullmatch(r'/dev/[A-Za-z0-9_-]+', disk) else None
        self.clock = clock
        self.started = self.previous_time = clock()
        self.started_wall = time.time()
        self.baseline = self.previous_bytes = self.disk_bytes()
        self.offset = log_offset
        self.progress = None
        self.details = {}

    def disk_bytes(self):
        if not self.disk:
            return None
        try:
            values = (Path('/sys/class/block') / Path(self.disk).name / 'stat').read_text().split()
            return int(values[6]) * 512
        except (OSError, ValueError, IndexError):
            return None

    def sample(self):
        now = self.clock()
        written = self.disk_bytes()
        metrics = {'elapsed_seconds': max(0, int(now - self.started)),
                   'write_bps': None, 'disk_written_bytes': None, 'eta': None}
        if written is not None and (self.baseline is None or (self.previous_bytes is not None and written < self.previous_bytes)):
            self.baseline = written
        if written is not None and self.previous_bytes is not None and written >= self.previous_bytes:
            if now > self.previous_time:
                metrics['write_bps'] = (written - self.previous_bytes) / (now - self.previous_time)
            if self.baseline is not None:
                metrics['disk_written_bytes'] = max(0, written - self.baseline)
        self.previous_bytes, self.previous_time = written, now
        candidates = [self.root / 'display-content-old.txt']
        candidates += list((self.root / 'display-content').glob('*.txt'))
        newest = []
        for path in candidates:
            try:
                stamp = path.stat().st_mtime
                if stamp >= self.started_wall:
                    newest.append((stamp, path))
            except OSError:
                pass
        for _, path in sorted(newest, reverse=True)[:8]:
            try:
                text = path.read_text(encoding='utf-8', errors='replace')[:16384]
            except OSError:
                continue
            parsed = parse_progress(text)
            if parsed:
                self.progress = parsed.pop('progress')
                self.details = parsed
                break
        phase = self.details.get('phase', 'Preparando respaldo')
        if not self.details:
            try:
                with (self.root / 'little-backup-box.log').open('rb') as log:
                    size = log.seek(0, 2)
                    log.seek(max(self.offset if size >= self.offset else 0, size - 8192))
                    tail = ' '.join(log.read().decode('utf-8', errors='replace').lower().split())
                if tail.endswith('ready insert target'):
                    phase = 'Esperando disco de destino'
                elif tail.endswith('ready insert source'):
                    phase = 'Esperando origen'
            except OSError:
                pass
        metrics.update(self.details)
        return {'progress': self.progress, 'message': phase, 'metrics': metrics}
