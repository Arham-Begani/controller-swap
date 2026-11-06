import json
import os
import unittest
import urllib.error
from unittest.mock import patch

from controller_swap.core import evidence_view, fixture_pack
from controller_swap.evaluator import evaluator_schema
from controller_swap.models import ModelConnector, ModelRequestError
from controller_swap.server import Application
from tests import test_model_settings
from tests.test_server import FakeResponse


class EvaluatorTests(unittest.TestCase):
    def test_schema_depends_only_on_visible_evidence(self):
        runs = fixture_pack()
        pair = [next(r for r in runs if r['task'] == 'issues' and r['mode'] == mode
                     and r['worker'] == 'worker_a' and r['repetition'] == 1)
                for mode in ('human_steps', 'ai_steps')]
        schemas = [evaluator_schema(evidence_view(r, 'actions')) for r in pair]
        self.assertEqual(schemas[0], schemas[1])
        self.assertEqual(len(schemas[0]['anyOf']), 4)
        self.assertNotIn('worker_a', json.dumps(schemas[0]))
        self.assertEqual(schemas[0]['anyOf'][0]['properties']['evidence']['items']['enum'],
                         [e['record_ref'] for e in evidence_view(pair[0], 'actions')['events']])

    def test_generation_contract_keeps_all_labels_and_couples_compatible_sets(self):
        schema = evaluator_schema(evidence_view(fixture_pack()[0], 'actions'))
        branches = {b['properties']['label']['const']: b for b in schema['anyOf']}
        self.assertEqual(set(branches), {'human_steps','standing_instruction','ai_steps','unresolved'})
        for label in ('human_steps','standing_instruction','ai_steps'):
            self.assertEqual(branches[label]['properties']['compatible'], {'const': [label]})
        choices = branches['unresolved']['properties']['compatible']['enum']
        self.assertEqual(len(choices), 7)
        self.assertTrue(all(len(x) == len(set(x)) and x for x in choices))

    def test_observed_bad_labels_are_retained_not_repaired(self):
        app = Application(':memory:', live=True)
        try:
            run = fixture_pack()[0]; app.store.put(run)
            bad = {'label': 'human_steps', 'compatible': ['human intermediate choices'],
                   'evidence': ['v0'], 'reason': 'Invalid provider label'}
            with patch.object(app.models, 'ask', return_value=bad):
                result = app.evaluate_model({'method': 'model_evidence', 'view': 'actions',
                                             'scope': 'synthetic_fixture', 'split': 'development', 'limit': 1})
            self.assertEqual(result['evaluated'], 0)
            self.assertEqual(result['failures'][0]['error_kind'], 'schema')
            self.assertEqual(app.store.predictions(), [])
            self.assertGreaterEqual(app.store.attempts()[0]['elapsed_seconds'], 0)
        finally:
            app.store.close()

    def test_explicit_evaluator_timeout_and_schema_on_wire(self):
        connector = ModelConnector(True)
        response = json.dumps({'choices': [{'message': {'content': '{}'}}]}).encode()
        schema = evaluator_schema(evidence_view(fixture_pack()[0], 'actions'))
        config = test_model_settings.ModelSettingsTests.config | {'CS_EVALUATOR_TIMEOUT_SECONDS': '630', 'CS_RESPONSE_FORMAT': 'json_schema'}
        with patch.dict(os.environ, config), patch.object(connector.opener, 'open', side_effect=[FakeResponse(response), FakeResponse(response)]) as call:
            connector.ask('evaluator', 'Return JSON', {}, output_schema=schema)
            self.assertEqual(call.call_args.kwargs['timeout'], 630)
            sent = json.loads(call.call_args.args[0].data)
            self.assertEqual(sent['response_format']['json_schema']['schema'], schema)
            self.assertEqual(connector.last_response_metadata['request_timeout_seconds'], 630)
            connector.ask('worker_a', 'Return JSON', {})
            self.assertEqual(call.call_args.kwargs['timeout'], 45)

    def test_invalid_evaluator_timeout_makes_no_request(self):
        for value in ('0', '901', 'nan'):
            connector = ModelConnector(True)
            with patch.dict(os.environ, test_model_settings.ModelSettingsTests.config | {'CS_EVALUATOR_TIMEOUT_SECONDS': value}), patch.object(connector.opener, 'open') as call:
                with self.assertRaises(ValueError):
                    connector.ask('evaluator', 'Return JSON', {})
                call.assert_not_called()

    def test_truncated_or_malformed_output_is_not_accepted(self):
        for body in ({'choices': [{'finish_reason': 'length', 'message': {'content': '{}'}}]},
                     {'choices': ['invalid']}, {'choices': []}):
            connector = ModelConnector(True)
            with patch.dict(os.environ, test_model_settings.ModelSettingsTests.config), patch.object(connector.opener, 'open', return_value=FakeResponse(json.dumps(body).encode())):
                with self.assertRaises(ModelRequestError):
                    connector.ask('evaluator', 'Return JSON', {})

    def test_http_timeouts_keep_request_metadata_without_provider_secrets(self):
        for code, kind in ((408, 'timeout'), (504, 'timeout'), (503, 'transport')):
            connector = ModelConnector(True)
            error = urllib.error.HTTPError('https://private.example/secret', code, 'sensitive body', {}, None)
            with patch.dict(os.environ, test_model_settings.ModelSettingsTests.config), patch.object(connector.opener, 'open', side_effect=error):
                with self.assertRaises(ModelRequestError) as caught:
                    connector.ask('evaluator', 'Return JSON', {})
            self.assertEqual(caught.exception.kind, kind)
            self.assertNotIn('sensitive', str(caught.exception))
            self.assertNotIn('private', str(caught.exception))
            metadata = connector.last_response_metadata
            self.assertEqual(metadata['request_timeout_seconds'], 45)
            self.assertEqual(len(metadata['messages_sha256']), 64)
            self.assertGreaterEqual(metadata['elapsed_seconds'], 0)
            self.assertIn('max_tokens', metadata['request_parameters'])
