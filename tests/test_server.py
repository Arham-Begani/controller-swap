import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from io import BytesIO
from unittest.mock import patch

from controller_swap.core import digest
from controller_swap.models import ModelConnector
from controller_swap.server import Application, make_server


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.app = Application(os.path.join(cls.temp.name, 'test.sqlite3'))
        cls.server = make_server(cls.app, 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.app.store.close()
        cls.temp.cleanup()

    def request(self, path, data=None, token=True, origin=None):
        headers = {}
        if token:
            headers['X-CS-Token'] = self.app.token
        if origin:
            headers['Origin'] = origin
        request = urllib.request.Request(self.base + path, data=None if data is None else json.dumps(data).encode(), headers=headers)
        with urllib.request.urlopen(request) as response:
            return json.load(response)

    def test_http_interactive_session_to_evidence_and_export(self):
        run = self.request('/api/runs', {'task': 'issues', 'mode': 'human_steps', 'worker': 'worker_a'})
        for record, value in [('I1', 'ready'), ('I2', 'hold'), ('I3', 'hold'), ('I4', 'ready')]:
            run = self.request('/api/runs/' + run['id'] + '/step', {'action': {'record': record, 'value': value}})
        self.assertEqual(run['status'], 'complete')
        view = self.request('/api/runs/' + run['id'] + '/view?view=actions')
        self.assertEqual(len(view['events']), 8)
        bundle = self.request('/api/export')
        claimed = bundle.pop('content_sha256')
        self.assertEqual(claimed, digest(bundle))
        self.assertNotIn('token', bundle)

    def test_mutation_rejects_missing_token_and_foreign_origin(self):
        for token, origin in [(False, None), (True, 'https://unrelated.example')]:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request('/api/demo', {}, token=token, origin=origin)
            self.assertEqual(caught.exception.code, 403)

    def test_live_requests_disabled(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request('/api/runs', {'task': 'issues', 'mode': 'ai_steps', 'worker': 'worker_a', 'backend': 'model'})
        self.assertEqual(caught.exception.code, 400)
        self.assertEqual(self.app.models.calls, 0)

    def test_demo_generation_is_idempotent_and_evaluable(self):
        self.request('/api/demo', {})
        self.assertEqual(self.request('/api/demo', {})['added'], 0)
        p = self.request('/api/evaluate', {'view': 'actions', 'method': 'evidence_checklist'})
        self.assertGreaterEqual(p['evaluated'], 72)
        analysis = self.request('/api/analysis')
        self.assertTrue(all(s['coverage'] == 0 for s in analysis['summaries'] if s['method'] == 'evidence_checklist'))

    def test_import_validation_is_atomic(self):
        run = self.request('/api/runs', {'task': 'issues', 'mode': 'standing_instruction', 'worker': 'worker_a'})
        before = len(self.app.store.predictions())
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/predictions/import', {'predictions': [
                {'run_id': run['id'], 'view': 'actions', 'label': 'unresolved'},
                {'run_id': run['id'], 'view': 'actions', 'label': 'invented'}]})
        self.assertEqual(len(self.app.store.predictions()), before)

    def test_static_boundary(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request('/../../README.md')
        self.assertEqual(caught.exception.code, 404)

    def test_browser_favicon_request_is_handled(self):
        with urllib.request.urlopen(self.base + '/favicon.ico') as response:
            self.assertEqual(response.status, 204)
            self.assertEqual(response.read(), b'')

    def test_model_evaluator_receives_only_selected_evidence(self):
        self.request('/api/demo', {})
        response = {'label': 'unresolved', 'compatible': ['human_steps', 'standing_instruction', 'ai_steps'], 'evidence': [], 'reason': 'Insufficient source evidence'}
        with patch.object(self.app.models, 'enabled', True), patch.object(self.app.models, 'ask', return_value=response) as mocked:
            result = self.request('/api/evaluate', {'method': 'model_evidence', 'view': 'actions', 'limit': 1, 'scope': 'synthetic_fixture'})
            self.assertEqual(result['evaluated'], 1)
            payload = mocked.call_args.args[2]
            self.assertNotIn('arrangement', json.dumps(payload))
            self.assertNotIn('worker_alias', json.dumps(payload))
            self.assertNotIn('run_id', payload)
        self.assertEqual(self.app.store.attempts()[-1]['status'], 'saved')

    def test_model_evaluator_retains_failures(self):
        self.request('/api/demo', {})
        with patch.object(self.app.models, 'enabled', True), patch.object(self.app.models, 'ask', side_effect=ValueError('Invalid model response')):
            result = self.request('/api/evaluate', {'method': 'model_generic', 'view': 'actions', 'limit': 1, 'scope': 'synthetic_fixture'})
        self.assertEqual(result['evaluated'], 0)
        self.assertEqual(len(result['failures']), 1)
        self.assertEqual(self.app.store.attempts()[-1]['status'], 'failed')

    def test_failed_model_step_is_retained_without_advancing_state(self):
        from controller_swap.core import new_run, verify_chain
        run = new_run('issues', 'standing_instruction', 'worker_a', backend='model')
        self.app.store.put(run)
        with patch.object(self.app.models, 'ask', side_effect=ValueError('Provider returned invalid JSON')):
            with self.assertRaises(ValueError):
                self.app.step(run['id'], {})
        stored = self.app.store.get(run['id'])
        self.assertEqual(stored['state'], {})
        self.assertEqual(stored['events'][-1]['kind'], 'attempt_error')
        self.assertTrue(verify_chain(stored))


class FakeResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class ConnectorTests(unittest.TestCase):
    config = {'CS_MODEL_BASE_URL': 'http://127.0.0.1:12345/v1', 'CS_WORKER_A': 'model-a', 'CS_WORKER_B': 'model-b', 'CS_MODEL_API_KEY': 'test-secret'}

    def test_adapter_contract_and_call_limit_without_network(self):
        response = json.dumps({'choices': [{'message': {'content': '{"record":"I1","value":"ready"}'}}]}).encode()
        connector = ModelConnector(enabled=True, max_calls=1)
        with patch.dict(os.environ, self.config), patch('urllib.request.OpenerDirector.open', return_value=FakeResponse(response)) as mocked:
            self.assertEqual(connector.ask('worker_a', 'instruction', {})['record'], 'I1')
            sent = json.loads(mocked.call_args.args[0].data)
            self.assertEqual(sent['model'], 'model-a')
            self.assertEqual(sent['max_completion_tokens'], 1024)
            with self.assertRaises(ValueError):
                connector.ask('worker_b', 'instruction', {})
        self.assertEqual(connector.calls, 1)

    def test_adapter_failure_does_not_echo_provider_secrets(self):
        with patch.dict(os.environ, self.config), patch('urllib.request.OpenerDirector.open', side_effect=urllib.error.URLError('test-secret')):
            with self.assertRaises(ValueError) as caught:
                ModelConnector(True).ask('worker_a', '', {})
            self.assertNotIn('test-secret', str(caught.exception))

    def test_remote_plain_http_is_rejected(self):
        config = self.config | {'CS_MODEL_BASE_URL': 'http://remote.example/v1'}
        with patch.dict(os.environ, config):
            with self.assertRaises(ValueError):
                ModelConnector(True).ask('worker_a', '', {})

    def test_invalid_token_cap_prevents_network_request(self):
        with patch.dict(os.environ, self.config | {'CS_MAX_COMPLETION_TOKENS': '0'}), patch('urllib.request.OpenerDirector.open') as mocked:
            with self.assertRaises(ValueError):
                ModelConnector(True).ask('worker_a', '', {})
            mocked.assert_not_called()


if __name__ == '__main__':
    unittest.main()
