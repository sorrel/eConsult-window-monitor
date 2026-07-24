import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from monitor import fetch


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/ok":
            body = b"<html><body>hello</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/redir":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"nope")

    def log_message(self, *args):  # silence test server logging
        pass


@pytest.fixture()
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    yield f"http://{host}:{port}"
    httpd.shutdown()


def test_fetch_returns_body_and_status(server):
    result = fetch.fetch(f"{server}/ok", "test-agent/0.1")
    assert result.status == 200
    assert "hello" in result.body
    assert result.error is None
    assert result.latency_ms >= 0


def test_fetch_follows_redirect(server):
    result = fetch.fetch(f"{server}/redir", "test-agent/0.1")
    assert result.status == 200
    assert "hello" in result.body
    assert result.final_url.endswith("/ok")


def test_fetch_never_raises_on_connection_error():
    # Nothing listening on this port; must return an error result, not raise.
    result = fetch.fetch("http://127.0.0.1:1/never", "test-agent/0.1", timeout=2)
    assert result.status is None
    assert result.error is not None
    assert result.body == ""
