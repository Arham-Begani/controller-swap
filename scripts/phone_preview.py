"""Private-network sample preview; never opens the saved research database.

Run: python -m scripts.phone_preview --host <computer Wi-Fi IPv4>
The normal workbench remains loopback-only. This opt-in adapter requires an
ephemeral access link and same-origin POSTs, retaining the normal CSRF token.
"""
import argparse
from datetime import datetime, timezone
from http.cookies import SimpleCookie, CookieError
from http.server import ThreadingHTTPServer
from ipaddress import ip_address, ip_network
import json
from pathlib import Path
import secrets
import tempfile
from urllib.parse import parse_qs, urlparse

from controller_swap.server import Application, make_server

COOKIE = 'cs_phone_preview'
PRIVATE_NETWORKS = tuple(ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def make_preview(app, host, port=8786, access_token=None):
    if app.models.enabled:
        raise ValueError('Phone preview requires disabled live models')
    access_token = access_token or secrets.token_urlsafe(24)
    # Reuse the existing application handler; do not run a duplicate backend.
    base = make_server(app, 0)
    base_handler = base.RequestHandlerClass
    base.server_close()

    class PreviewHandler(base_handler):
        def setup(self):
            super().setup()
            self.connection.settimeout(20)

        def end_headers(self):
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-CS-Preview', 'synthetic-only')
            super().end_headers()

        def valid_host(self):
            return self.headers.get('Host') == f'{host}:{self.server.server_port}'

        def same_origin(self):
            return self.headers.get('Origin') == f'http://{host}:{self.server.server_port}'

        def authenticated(self):
            try:
                cookie = SimpleCookie()
                cookie.load(self.headers.get('Cookie', ''))
                value = cookie[COOKIE].value if COOKIE in cookie else ''
                return secrets.compare_digest(value.encode(), access_token.encode())
            except (CookieError, UnicodeError):
                return False

        def do_GET(self):
            parsed = urlparse(self.path)
            if not self.valid_host() or parsed.netloc or not self.path.startswith('/'):
                return self.respond({'error': 'Use the exact Wi-Fi preview address'}, 403)
            if self.headers.get('Origin') and not self.same_origin():
                return self.respond({'error': 'Cross-origin requests are not allowed'}, 403)
            values = parse_qs(parsed.query).get('preview', [])
            if parsed.path == '/' and len(values) == 1 and secrets.compare_digest(values[0].encode(), access_token.encode()):
                self.send_response(303)
                self.send_header('Location', '/')
                # Lax permits the top-level GET redirect after tapping a link in
                # chat. POSTs still require exact Origin plus the CSRF token.
                self.send_header('Set-Cookie', f'{COOKIE}={access_token}; Path=/; HttpOnly; SameSite=Lax')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            if not self.authenticated():
                return self.respond({'error': 'Open the complete private preview link supplied for this session'}, 403)
            return super().do_GET()

        def do_POST(self):
            if not self.valid_host() or not self.authenticated():
                return self.respond({'error': 'Open the complete private preview link first'}, 403)
            if not self.same_origin():
                return self.respond({'error': 'Same-origin browser requests are required'}, 403)
            if self.headers.get('Transfer-Encoding'):
                return self.respond({'error': 'Transfer-Encoding is not supported'}, 400)
            # Origin has been checked against the exact LAN origin. Normalize only
            # for the unchanged parent handler's loopback Origin check. Its token
            # validation, body size limits and application rules still apply.
            original = self.headers['Origin']
            self.headers.replace_header('Origin', f'http://127.0.0.1:{self.server.server_port}')
            try:
                return super().do_POST()
            finally:
                self.headers.replace_header('Origin', original)

    server = ThreadingHTTPServer((host, port), PreviewHandler)
    server.daemon_threads = True
    return server, access_token


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True, help='Computer Wi-Fi IPv4; only RFC1918 addresses are accepted')
    parser.add_argument('--port', type=int, default=8786)
    args = parser.parse_args()
    address = ip_address(args.host)
    if address.version != 4 or not any(address in network for network in PRIVATE_NETWORKS):
        parser.error('Bind to an explicit private Wi-Fi IPv4 address, never a wildcard or public address')
    with tempfile.TemporaryDirectory(prefix='controller-swap-phone-') as directory:
        app = Application(str(Path(directory) / 'sample.sqlite3'), live=False)
        server, token = make_preview(app, str(address), args.port)
        info = dict(url=f'http://{address}:{server.server_port}/?preview={token}',
                    started_utc=datetime.now(timezone.utc).isoformat(),
                    database='Temporary isolated sample database; discarded when the preview stops',
                    live_models=False, edition='Motion edition / 02')
        state = Path(__file__).resolve().parents[1] / '.runtime/phone-preview.json'
        state.parent.mkdir(exist_ok=True)
        state.write_text(json.dumps(info, indent=2), encoding='utf-8')
        print(json.dumps(info, indent=2), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            app.store.close()


if __name__ == '__main__':
    main()
