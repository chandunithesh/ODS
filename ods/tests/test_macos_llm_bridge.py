from __future__ import annotations

import importlib.util
import socketserver
import threading
import urllib.request
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "bin" / "ods-macos-llm-bridge.py"
SPEC = importlib.util.spec_from_file_location("ods_macos_llm_bridge", MODULE_PATH)
assert SPEC and SPEC.loader
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


class _HttpHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        self.request.recv(4096)
        body = b'{"status":"ok"}'
        self.request.sendall(
            b"HTTP/1.1 200 OK\r\n"
            + f"Content-Length: {len(body)}\r\n".encode()
            + b"Connection: close\r\n\r\n"
            + body
        )


def test_peer_allowlist_is_loopback_only():
    assert bridge.peer_is_allowed("127.0.0.1") is True
    assert bridge.peer_is_allowed("::1") is True
    assert bridge.peer_is_allowed("192.168.5.2") is False
    assert bridge.peer_is_allowed("192.168.1.50") is False
    assert bridge.peer_is_allowed("not-an-ip") is False


def test_bridge_forwards_loopback_http():
    upstream = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _HttpHandler)
    proxy = bridge.LlmBridgeServer(
        ("127.0.0.1", 0),
        ("127.0.0.1", upstream.server_address[1]),
    )
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    upstream_thread.start()
    proxy_thread.start()
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{proxy.server_address[1]}/health",
            timeout=5,
        ) as response:
            assert response.read() == b'{"status":"ok"}'
    finally:
        proxy.shutdown()
        upstream.shutdown()
        proxy.server_close()
        upstream.server_close()
