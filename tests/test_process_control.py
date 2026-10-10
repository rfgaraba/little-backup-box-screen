import signal
import unittest
from unittest.mock import Mock, patch
from process_control import stop_group


class ProcessControlTests(unittest.TestCase):
    def test_cancel_signals_own_group_and_reaps_leader(self):
        process = Mock(pid=123)
        with patch('process_control.group_alive', side_effect=[True, True, False, False, False]), patch('process_control.os.killpg') as kill, patch('process_control.time.sleep'):
            stop_group(process)
        kill.assert_called_once_with(123, signal.SIGTERM)
        process.poll.assert_called_once()

    def test_already_exited_group_needs_no_signal(self):
        with patch('process_control.group_alive', return_value=False), patch('process_control.os.killpg') as kill:
            stop_group(Mock(pid=123))
        kill.assert_not_called()

    def test_does_not_signal_system_process_group(self):
        with patch('process_control.os.killpg') as kill:
            with self.assertRaises(ValueError):
                stop_group(Mock(pid=1))
        kill.assert_not_called()

    def test_unstopped_children_keep_removal_blocked(self):
        with patch('process_control.group_alive', return_value=True), patch('process_control.os.killpg') as kill, patch('process_control.time.monotonic', side_effect=[0, 11, 11, 15]):
            with self.assertRaises(ValueError):
                stop_group(Mock(pid=123))
        self.assertEqual([call.args[1] for call in kill.call_args_list], [signal.SIGTERM, signal.SIGKILL])
