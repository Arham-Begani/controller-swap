import json
import os
import unittest
from unittest.mock import patch

from controller_swap.models import ModelConnector
from tests.test_server import FakeResponse


class ModelSettingsTests(unittest.TestCase):
    config = {'CS_MODEL_BASE_URL': 'http://127.0.0.1:12345/v1', 'CS_WORKER_A': 'test-model',
              'CS_WORKER_B': 'test-model', 'CS_MODEL_API_KEY': '', 'CS_MAX_COMPLETION_TOKENS': '256',
              'CS_TOKEN_PARAMETER': 'max_tokens', 'CS_RESPONSE_FORMAT': 'json_object',
              'CS_TEMPERATURE': '0.7', 'CS_SEED': '73007'}

    def test_actual_options_are_bound_to_response_metadata(self):
        response = json.dumps({'model': 'test-model', 'choices': [{'message': {'content': '{}'}}]}).encode()
        connector = ModelConnector(True)
        with patch.dict(os.environ, self.config), patch.object(connector.opener, 'open', return_value=FakeResponse(response)) as call:
            self.assertEqual(connector.ask('worker_a', 'Only JSON', {}), {})
        sent = json.loads(call.call_args.args[0].data)
        self.assertEqual(sent['response_format'], {'type': 'json_object'})
        self.assertEqual(sent['temperature'], 0.7)
        self.assertEqual(sent['seed'], 73007)
        metadata = connector.last_response_metadata
        self.assertEqual(metadata['request_parameters']['max_tokens'], 256)
        self.assertEqual(len(metadata['messages_sha256']), 64)

    def test_invalid_or_nonfinite_options_do_not_call_provider(self):
        for option in ({'CS_TEMPERATURE': 'nan'}, {'CS_TEMPERATURE': 'inf'}, {'CS_TEMPERATURE': '-1'},
                       {'CS_SEED': 'not-int'}, {'CS_SEED': '2147483648'}, {'CS_RESPONSE_FORMAT': 'unsupported'},
                       {'CS_REQUEST_TIMEOUT_SECONDS': '0'}, {'CS_REQUEST_TIMEOUT_SECONDS': '181'}, {'CS_REQUEST_TIMEOUT_SECONDS': 'nan'}):
            connector = ModelConnector(True)
            with patch.dict(os.environ, self.config | option), patch.object(connector.opener, 'open') as call:
                with self.assertRaises(ValueError):
                    connector.ask('worker_a', 'Only JSON', {})
                call.assert_not_called()
                self.assertEqual(connector.calls, 0)
