#!/usr/bin/env python3
"""Loopback-filtered TCP bridge for Colima to reach macOS-native llama-server."""

from __future__ import annotations

import argparse
import ipaddress
import logging
import signal
import socket
import socketserver
import threading

logger = logging.getLogger("ods-macos-llm-bridge")


def peer_is_allowed(address: str) -> bool:
    """Only local forwarding helpers may cross the wildcard listener."""
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def _pump(source: socket.socket, destination: socket.socket) -> None:
    try:
        while True:
            data = source.recv(65536)
            if not data:
                break
            destination.sendall(data)
    except (ConnectionError, OSError):
        pass
    finally:
        try:
            destination.shutdown(socket.SHUT_WR)
        except OSError:
            pass


class LlmBridgeHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        peer = str(self.client_address[0])
        if not peer_is_allowed(peer):
            logger.warning("Rejected non-loopback bridge client %s", peer)
            return

        server = self.server
        try:
            upstream = socket.create_connection(
                (server.target_host, server.target_port),  # type: ignore[attr-defined]
                timeout=10,
            )
        except OSError as exc:
            logger.debug("Native llama-server is not ready: %s", exc)
            return

        with upstream:
            self.request.settimeout(None)
            upstream.settimeout(None)
            request_to_upstream = threading.Thread(
                target=_pump,
                args=(self.request, upstream),
                daemon=True,
            )
            upstream_to_request = threading.Thread(
                target=_pump,
                args=(upstream, self.request),
                daemon=True,
            )
            request_to_upstream.start()
            upstream_to_request.start()
            request_to_upstream.join()
            upstream_to_request.join()


class LlmBridgeServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        target_address: tuple[str, int],
    ) -> None:
        self.target_host, self.target_port = target_address
        super().__init__(server_address, LlmBridgeHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description="ODS macOS Colima LLM bridge")
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=8080)
    parser.add_argument("--target-host", default="127.0.0.1")
    parser.add_argument("--target-port", type=int, default=18080)
    args = parser.parse_args()

    if args.listen_port == args.target_port:
        parser.error("listen and target ports must differ")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    server = LlmBridgeServer(
        (args.listen_host, args.listen_port),
        (args.target_host, args.target_port),
    )

    def request_shutdown(signum, _frame) -> None:
        logger.info("Received signal %s; shutting down", signum)
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    logger.info(
        "Listening on %s:%d for loopback peers; forwarding to %s:%d",
        args.listen_host,
        args.listen_port,
        args.target_host,
        args.target_port,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
