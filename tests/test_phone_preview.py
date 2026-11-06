"""LAN adapter gates tested over real HTTP on an isolated loopback test socket."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from controller_swap.server import Application
from scripts.phone_preview import make_preview, COOKIE


class PhonePreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.app = Application(str(Path(cls.temp.name) / 'test.sqlite3'))
        cls.server, cls.key = make_preview(cls.app, '127.0.0.1', 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.host = f'127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()
        cls.app.store.close(); cls.temp.cleanup()

    def request(self, path='/', method='GET', body=None, auth=True, **headers):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        h = {'Host': self.host}
        if auth: h['Cookie'] = f'{COOKIE}={self.key}'
        if method == 'POST':
            h.update({'Origin': 'http://' + self.host, 'X-CS-Token': self.app.token, 'Content-Type': 'application/json'})
        h.update(headers)
        connection.request(method, path, json.dumps(body) if body is not None else None, headers=h)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_access_link_cookie_and_redirect(self):
        status, headers, _ = self.request('/?preview=' + self.key, auth=False)
        self.assertEqual(status, 303)
        self.assertEqual(headers['Location'], '/')
        self.assertIn('HttpOnly; SameSite=Lax', headers['Set-Cookie'])
        self.assertEqual(headers['Referrer-Policy'], 'no-referrer')

    def test_auth_host_origin_and_csrf_gates(self):
        self.assertEqual(self.request(auth=False)[0], 403)
        self.assertEqual(self.request('/?preview=wrong', auth=False)[0], 403)
        self.assertEqual(self.request(Host='attacker.test')[0], 403)
        self.assertEqual(self.request(Origin='http://attacker.test')[0], 403)
        self.assertEqual(self.request('/api/demo', 'POST', {}, auth=False)[0], 403)
        self.assertEqual(self.request('/api/demo', 'POST', {}, Origin='http://attacker.test')[0], 403)
        self.assertEqual(self.request('/api/demo', 'POST', {}, Origin='')[0], 403)
        self.assertEqual(self.request('/api/demo', 'POST', {}, **{'X-CS-Token': 'wrong'})[0], 403)

    def test_assets_restricted_to_allowlist(self):
        for asset, content_type in [('/motion.css','text/css'),('/fonts/fraunces-regular.woff2','font/woff2'),('/fonts/fraunces-italic.woff2','font/woff2'),('/fonts/manrope-latin.woff2','font/woff2')]:
            status, headers, body = self.request(asset)
            self.assertEqual(status, 200)
            self.assertTrue(headers['Content-Type'].startswith(content_type))
            self.assertGreater(len(body), 100)
        for path in ('/data/controller-swap.sqlite3', '/fonts/../../server.py', '/.runtime/phone-preview.json'):
            self.assertEqual(self.request(path)[0], 404)

    def test_sample_creation_without_live_models(self):
        status, headers, body = self.request('/api/status')
        self.assertEqual(status, 200)
        self.assertEqual(headers['X-CS-Preview'], 'synthetic-only')
        self.assertFalse(json.loads(body)['model']['enabled'])
        status, _, body = self.request('/api/runs', 'POST', {'task':'files','mode':'human_steps','worker':'worker_a','backend':'fixture','repetition':1})
        self.assertEqual(status, 201)
        self.assertEqual(json.loads(body)['scope'], 'interactive_fixture')
        self.assertEqual(self.request('/api/runs', 'POST', {'task':'files','mode':'human_steps','worker':'worker_a','backend':'model'})[0], 400)
        self.assertEqual(self.app.models.calls, 0)
