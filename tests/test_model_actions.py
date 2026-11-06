import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from controller_swap.core import new_run, record_step, verify_chain
from controller_swap.server import Application
from controller_swap.tasks import public_task


class ModelActionTests(unittest.TestCase):
    def test_model_sees_available_choices_without_answer_key(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Application(str(Path(directory) / 'test.sqlite3'))
            try:
                run = new_run('issues', 'standing_instruction', 'worker_a', backend='model')
                record_step(run, worker_action={'record': 'I1', 'value': 'ready'})
                app.store.put(run)
                with patch.object(app.models, 'ask', return_value={'record': 'I2', 'value': 'hold'}) as ask:
                    result = app.step(run['id'], {})
                    payload = ask.call_args.args[2]
                    self.assertEqual(payload['available_record_ids'], ['I2', 'I3', 'I4'])
                    self.assertEqual([r['id'] for r in payload['task']['records']], ['I2', 'I3', 'I4'])
                    self.assertEqual(payload['past_state']['I1'], 'ready')
                    self.assertNotIn('answers', payload['task'])
                    self.assertEqual(len(public_task('issues')['records']), 4)
                    self.assertTrue(verify_chain(result))
            finally:
                app.store.close()

    def test_invalid_supervisor_choice_stops_before_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Application(str(Path(directory) / 'test.sqlite3'))
            try:
                run = new_run('issues', 'ai_steps', 'worker_a', backend='model')
                choice = {'record': 'I1', 'value': 'ready'}
                record_step(run, controller_action=choice, worker_action=choice)
                app.store.put(run)
                with patch.object(app.models, 'ask', return_value=choice) as ask:
                    with self.assertRaisesRegex(ValueError, 'already processed'):
                        app.step(run['id'], {})
                    self.assertEqual(ask.call_count, 1)
                    self.assertEqual(ask.call_args.args[0], 'supervisor')
                stored = app.store.get(run['id'])
                self.assertEqual(stored['state'], {'I1': 'ready'})
                self.assertEqual(stored['events'][-1]['kind'], 'attempt_error')
                self.assertTrue(verify_chain(stored))
            finally:
                app.store.close()
