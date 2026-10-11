import unittest
from server import backup_result


class BackupResultTests(unittest.TestCase):
    def test_completed_summary_confirms_success_after_retry(self):
        result = backup_result(0, 'Exception: earlier error\nBackup complete.\n250 of 248 files copied\n1 failed attempts')
        self.assertEqual(result['state'], 'success')

    def test_incomplete_or_nonzero_never_reports_success(self):
        self.assertEqual(backup_result(0, 'Backup complete.\n20 of 30 files copied')['state'], 'error')
        self.assertEqual(backup_result(1, 'Backup complete.\n30 of 30 files copied')['state'], 'error')
        self.assertEqual(backup_result(0, 'finished')['state'], 'review')
