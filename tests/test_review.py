"""Regression cases discovered by the second review, including real loopback HTTP.

The wire service below is a deterministic stub, never a language model.
"""
import copy
import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from controller_swap.audit import collision_audit
from controller_swap.core import (MODES, baseline, digest, evidence_view, fixture_pack,
                                  metrics, new_run, validate_prediction, verify_chain)
from controller_swap.models import ModelConnector
from controller_swap.server import Application, make_server
from controller_swap.tasks import expected_action


class ReviewMetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = fixture_pack()

    def test_exact_collision_counts_and_ceilings(self):
        rows = {r['view']: r for r in collision_audit(self.pack)['summaries']}
        for view, distinct, conflicts, maximum in [('actions', 8, 8, 16), ('messages', 16, 8, 32), ('complete', 24, 0, 48)]:
            row = rows[view]
            self.assertEqual((row['n'], row['distinct_inputs'], row['conflicting_inputs']), (48, distinct, conflicts))
            self.assertEqual(row['max_correct_from_input_alone'], maximum)
            self.assertEqual(row['empirical_accuracy_ceiling'], maximum / 48)
        by_id = {r['id']: r for r in self.pack}
        for group in rows['actions']['conflicts']:
            inputs = [evidence_view(by_id[k], 'actions') for k in group['run_ids']]
            self.assertTrue(all(x == inputs[0] for x in inputs))
            self.assertEqual(group['evidence_sha256'], digest(inputs[0]))

    def test_audit_preserves_scope_and_excludes_incomplete(self):
        active = new_run('files', 'human_steps', 'worker_a')
        alternate = copy.deepcopy(self.pack[-1])
        alternate.update(id='separate-scope', scope='interactive_fixture')
        rows = collision_audit(self.pack + [active, alternate])['summaries']
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(r['n'] == 1 for r in rows if r['scope'] == 'interactive_fixture'))

    def test_ambiguous_cell_does_not_multiply_pairs_even_if_unscored(self):
        runs = [r for r in self.pack if r['split'] == 'evaluation']
        predictions = [baseline(r, 'complete', 'evidence_checklist') for r in runs]
        extra = copy.deepcopy(runs[0]); extra['id'] = 'duplicate-cell'
        for scored in (False, True):
            ps = predictions + ([baseline(extra, 'complete', 'evidence_checklist')] if scored else [])
            row = metrics(runs + [extra], ps)['summaries'][0]
            self.assertEqual(row['ambiguous_pair_cells'], 1)
            self.assertEqual(row['worker_pairs'], 23)
            self.assertEqual(row['controller_pairs'], 46)

    def test_stale_predictions_are_excluded_and_legacy_is_explicit(self):
        run = self.pack[-1]
        prediction = baseline(run, 'actions', 'always_abstain')
        prediction['evidence_sha256'] = 'stale'
        row = metrics([run], [prediction])['summaries'][0]
        self.assertEqual(row['n'], 0)
        self.assertEqual(row['stale_predictions_excluded'], 1)
        self.assertIsNone(row['coverage'])
        del prediction['evidence_sha256']
        row = metrics([run], [prediction])['summaries'][0]
        self.assertEqual(row['legacy_unbound_predictions'], 1)

    def test_failed_only_group_does_not_disappear(self):
        run = self.pack[-1]
        attempts = [{'run_id': run['id'], 'method': 'model_generic', 'view': 'actions', 'status': 'failed'}]
        row = metrics([run], [], attempts=attempts)['summaries'][0]
        self.assertEqual((row['eligible_n'], row['missing_predictions'], row['failed_attempts']), (1, 1, 1))
        self.assertEqual(row['correct_over_eligible'], 0)
        self.assertIsNone(row['assigned_mode_accuracy'])
        self.assertIsNone(row['answered_error'])

    def test_import_rejects_stale_unfinished_and_malformed_sets(self):
        run = self.pack[-1]
        for malformed in ({'compatible': [{}]}, {'evidence_sha256': 'old'}):
            with self.assertRaises(ValueError):
                validate_prediction({'view': 'actions', 'label': 'unresolved'} | malformed, run)
        with self.assertRaises(ValueError):
            validate_prediction({'view': 'actions', 'label': 'unresolved'}, new_run('files', 'human_steps', 'worker_a'))


class EvaluationQueueTests(unittest.TestCase):
    def setUp(self):
        self.app = Application(':memory:', live=True)
        self.runs = [r for r in fixture_pack() if r['split'] == 'evaluation'][:3]
        for run in self.runs:
            self.app.store.put(run)
        self.body = {'method': 'model_evidence', 'view': 'actions', 'scope': 'synthetic_fixture', 'limit': 1}
        self.reply = {'label': 'unresolved', 'compatible': list(MODES), 'evidence': [], 'reason': 'No authenticated source in this view.'}

    def tearDown(self):
        self.app.store.close()

    def test_batches_advance_without_replacing_saved_predictions(self):
        with patch.object(self.app.models, 'ask', return_value=self.reply) as ask:
            first = self.app.evaluate_model(self.body)
            second = self.app.evaluate_model(self.body)
            self.assertNotEqual(first['selected_run_ids'], second['selected_run_ids'])
            self.assertEqual(ask.call_count, 2)
            self.assertEqual(len(self.app.store.predictions()), 2)
            self.assertEqual(second['pending_after_batch'], 1)

    def test_failed_run_requires_explicit_retry_and_retains_history(self):
        body = self.body | {'run_ids': [self.runs[0]['id']]}
        with patch.object(self.app.models, 'ask', side_effect=ValueError('Controlled failure')):
            self.assertEqual(self.app.evaluate_model(body)['attempted'], 1)
        with patch.object(self.app.models, 'ask', return_value=self.reply) as ask:
            self.assertEqual(self.app.evaluate_model(body)['attempted'], 0)
            ask.assert_not_called()
            self.assertEqual(self.app.evaluate_model(body | {'retry_failed': True})['evaluated'], 1)
        self.assertEqual([a['status'] for a in self.app.store.attempts()], ['failed', 'saved'])

    def test_default_scope_never_sends_fixtures_to_model(self):
        body = dict(self.body); del body['scope']
        with patch.object(self.app.models, 'ask') as ask:
            self.assertEqual(self.app.evaluate_model(body)['attempted'], 0)
            ask.assert_not_called()

    def test_invalid_target_ids_rejected_before_calls(self):
        with patch.object(self.app.models, 'ask') as ask:
            with self.assertRaises(ValueError):
                self.app.evaluate_model(self.body | {'run_ids': ['missing']})
            ask.assert_not_called()

    def test_trace_corruption_blocks_step_before_model_request(self):
        run = new_run('files', 'standing_instruction', 'worker_a', backend='model')
        run['events'][0]['data']['backend'] = 'edited'
        self.app.store.put(run)
        with patch.object(self.app.models, 'ask') as ask:
            with self.assertRaises(ValueError):
                self.app.step(run['id'], {})
            ask.assert_not_called()


class LoopbackWireTests(unittest.TestCase):
    def setUp(self):
        self.received = []
        received = self.received

        class Stub(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.append(request)
                if self.path.startswith('/redirect'):
                    self.send_response(307)
                    self.send_header('Location', '/v1/chat/completions')
                    self.end_headers()
                    return
                payload = json.loads(request['messages'][1]['content'])
                if 'events' in payload:
                    content = {'label': 'unresolved', 'compatible': list(MODES), 'evidence': [], 'reason': 'Simulated wire test only'}
                else:
                    task, state = payload['task'], payload['past_state']
                    record = next(r['id'] for r in task['records'] if r['id'] not in state)
                    content = payload.get('controller_action') or expected_action(task['id'], record)
                response = json.dumps({'model': 'deterministic-http-stub', 'choices': [{'message': {'content': json.dumps(content)}}], 'usage': {'total_tokens': 0}}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(response)))
                self.end_headers(); self.wfile.write(response)

        self.stub = ThreadingHTTPServer(('127.0.0.1', 0), Stub)
        self.thread = threading.Thread(target=self.stub.serve_forever, daemon=True)
        self.thread.start()
        self.config = {'CS_MODEL_BASE_URL': f'http://127.0.0.1:{self.stub.server_port}/v1',
                       'CS_WORKER_A': 'stub-a', 'CS_WORKER_B': 'stub-b', 'CS_MODEL_API_KEY': '',
                       'CS_SUPERVISOR': 'stub-supervisor', 'CS_EVALUATOR': 'stub-evaluator',
                       'CS_MAX_COMPLETION_TOKENS': '1024', 'CS_TOKEN_PARAMETER': 'max_completion_tokens'}

    def tearDown(self):
        self.stub.shutdown(); self.stub.server_close(); self.thread.join()

    def test_six_sessions_and_evaluation_through_actual_http(self):
        app = Application(':memory:', live=True)
        try:
            with patch.dict(os.environ, self.config):
                for worker in ('worker_a', 'worker_b'):
                    for mode in MODES:
                        run = new_run('files', mode, worker, backend='model')
                        app.store.put(run)
                        for record in ('F1', 'F2', 'F3', 'F4'):
                            body = {'action': expected_action('files', record)} if mode == 'human_steps' else {}
                            run = app.step(run['id'], body)
                        self.assertTrue(verify_chain(run))
                        self.assertEqual(run['status'], 'complete')
                        self.assertFalse(run['research_eligible'])
                result = app.evaluate_model({'method': 'model_evidence', 'view': 'actions', 'limit': 6})
                self.assertEqual(result['evaluated'], 6)
                self.assertEqual(app.models.calls, 38)
                self.assertEqual(len(self.received), 38)
                for request in self.received[-6:]:
                    payload = json.loads(request['messages'][1]['content'])
                    self.assertNotIn('arrangement', json.dumps(payload))
                    self.assertNotIn('worker_alias', json.dumps(payload))
                self.assertTrue(all(p['model_metadata']['reported_model'] == 'deterministic-http-stub' for p in app.store.predictions()))
        finally:
            app.store.close()

    def test_actual_redirect_is_rejected_without_followup(self):
        connector = ModelConnector(True)
        config = self.config | {'CS_MODEL_BASE_URL': f'http://127.0.0.1:{self.stub.server_port}/redirect'}
        with patch.dict(os.environ, config), self.assertRaisesRegex(ValueError, 'redirect'):
            connector.ask('worker_a', 'test', {})
        self.assertEqual(len(self.received), 1)

    def test_timeout_is_sanitized_and_old_metadata_cleared(self):
        connector = ModelConnector(True)
        connector.last_response_metadata = {'reported_model': 'old'}
        with patch.dict(os.environ, self.config), patch.object(connector.opener, 'open', side_effect=TimeoutError('sensitive-url')):
            with self.assertRaisesRegex(ValueError, 'Model request failed') as caught:
                connector.ask('worker_a', 'test', {})
            self.assertNotIn('sensitive', str(caught.exception))
        self.assertIsNone(connector.last_response_metadata['reported_model'])
        self.assertEqual(connector.last_response_metadata['request_timeout_seconds'], 45)
        self.assertGreaterEqual(connector.last_response_metadata['elapsed_seconds'], 0)

    def test_foreign_host_cannot_read_token_or_export(self):
        app = Application(':memory:')
        server = make_server(app, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            for path in ('/api/status', '/api/export'):
                request = urllib.request.Request(f'http://127.0.0.1:{server.server_port}{path}', headers={'Host': 'unrelated.example'})
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request)
                self.assertEqual(caught.exception.code, 403)
        finally:
            server.shutdown(); server.server_close(); thread.join(); app.store.close()
