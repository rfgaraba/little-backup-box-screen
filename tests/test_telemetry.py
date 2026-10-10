import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from telemetry import BackupTelemetry, parse_progress


class TelemetryTests(unittest.TestCase):
    def test_reads_file_progress_and_time_without_inventing_byte_percentage(self):
        data = parse_progress('s=hc:25 of 100, 12.3MB/s\ns=hc:Time remaining: 0:02:30\ns=hc:PGBAR=25.0')
        self.assertEqual(data['progress'], 25)
        self.assertEqual(data['files_processed'], 25)
        self.assertEqual(data['eta'], '0:02:30')
        self.assertIsNone(parse_progress('IMAGE=ip.png'))

    def test_unknown_total_does_not_show_misleading_percentage(self):
        self.assertIsNone(parse_progress('s=hc:25 de 100+, 12MB/s\nPGBAR=25')['progress'])

    def test_disk_write_speed_uses_counter_delta_and_elapsed_time(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(BackupTelemetry, 'disk_bytes', side_effect=[1000, 5001000, 5001000]):
            clock = iter([10, 12, 14])
            tracker = BackupTelemetry(tmp, '/dev/sda', clock=lambda: next(clock))
            first = tracker.sample()['metrics']
            self.assertEqual(first['write_bps'], 2500000)
            self.assertEqual(first['disk_written_bytes'], 5000000)
            self.assertEqual(tracker.sample()['metrics']['write_bps'], 0)

    def test_waiting_for_target_and_no_disk_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'tmp'
            root.mkdir()
            (root / 'little-backup-box.log').write_text('Ready\nInsert target\n')
            tracker = BackupTelemetry(tmp)
            data = tracker.sample()
            self.assertEqual(data['message'], 'Esperando disco de destino')
            self.assertIsNone(data['progress'])
            self.assertIsNone(data['metrics']['write_bps'])

    def test_stale_progress_is_ignored_and_current_progress_is_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'tmp'
            root.mkdir()
            progress = root / 'display-content-old.txt'
            progress.write_text('PGBAR=80')
            tracker = BackupTelemetry(tmp)
            tracker.started_wall = progress.stat().st_mtime + 1
            self.assertIsNone(tracker.sample()['progress'])
            tracker.started_wall = progress.stat().st_mtime - 1
            self.assertEqual(tracker.sample()['progress'], 80)
