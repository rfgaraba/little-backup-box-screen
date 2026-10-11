import subprocess
import unittest
from unittest.mock import patch
from server import Engine


class ShutdownTests(unittest.TestCase):
    def test_shutdown_only_queues_systemd_poweroff(self):
        engine = Engine({'engine_dir': '.'})
        with patch('server.subprocess.run') as run:
            engine.shutdown()
        self.assertTrue(engine.status()['shutting_down'])
        self.assertEqual(run.call_args.args[0], ['systemctl', 'poweroff', '--no-block'])
        with self.assertRaises(ValueError):
            engine.remove('anything')

    def test_shutdown_refused_for_active_jobs_removal_and_demo(self):
        with patch('server.subprocess.run') as run:
            for state in ('running', 'cancelling'):
                engine = Engine({'engine_dir': '.'})
                engine.job['state'] = state
                with self.assertRaises(ValueError):
                    engine.shutdown()
            engine.job['state'] = 'idle'
            engine.removing = True
            with self.assertRaises(ValueError):
                engine.shutdown()
            with self.assertRaises(ValueError):
                Engine().shutdown()
            run.assert_not_called()

    def test_failed_poweroff_releases_shutdown_state(self):
        engine = Engine({'engine_dir': '.'})
        with patch('server.subprocess.run', side_effect=subprocess.CalledProcessError(1, 'systemctl')):
            with self.assertRaises(ValueError):
                engine.shutdown()
        self.assertFalse(engine.status()['shutting_down'])
