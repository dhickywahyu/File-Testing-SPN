#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import asyncio
import signal
from contextlib import suppress
from typing import Optional, Set, Union
import argparse
import sys

import websockets
from websockets.server import WebSocketServerProtocol
from websockets.legacy.client import WebSocketClientProtocol  # compat with websockets<11

MessageT = Union[str, bytes]


class Relay:
    def __init__(
        self,
        upstream_uri: str,
        local_host: str = "0.0.0.0",
        local_port: int = 8004,
        bidirectional: bool = False,
        ping_interval: int = 20,
        ping_timeout: int = 20,
    ):
        self.upstream_uri = upstream_uri
        self.local_host = local_host
        self.local_port = local_port
        self.bidirectional = bidirectional
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout

        self.clients: Set[WebSocketServerProtocol] = set()
        self.upstream_ws: Optional[WebSocketClientProtocol] = None
        self.upstream_lock = asyncio.Lock()
        self.stop_event = asyncio.Event()
        self.server = None
        self.reader_task: Optional[asyncio.Task] = None

    async def broadcast(self, message: MessageT) -> None:
        """Send a message to all connected local clients."""
        if not self.clients:
            return
        dead = []
        for ws in list(self.clients):
            try:
                print(f"[relay] sending message to client: {message}")  # Print message being sent to client
                await ws.send(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)
            with suppress(Exception):
                await ws.close()

    async def connect_upstream(self) -> None:
        """(Re)connect to upstream with exponential backoff."""
        backoff = 1
        while not self.stop_event.is_set():
            try:
                print(f"[relay] connecting to upstream: {self.upstream_uri}")
                self.upstream_ws = await websockets.connect(
                    self.upstream_uri,
                    ping_interval=self.ping_interval,
                    ping_timeout=self.ping_timeout,
                    max_queue=64,
                )
                print("[relay] upstream connected")
                return
            except Exception as e:
                print(f"[relay] upstream connect failed: {e}; retry in {backoff}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def upstream_reader(self) -> None:
        """Read messages from upstream and broadcast to local clients. Reconnect on drop."""
        while not self.stop_event.is_set():
            # Ensure connected
            async with self.upstream_lock:
                if self.upstream_ws is None or self.upstream_ws.closed:
                    await self.connect_upstream()

            try:
                assert self.upstream_ws is not None
                async for message in self.upstream_ws:
                    print(f"[relay] received message from upstream: {message}")  # Print message received from upstream
                    await self.broadcast(message)
            except Exception as e:
                print(f"[relay] upstream read error: {e}")
            finally:
                # drop and reconnect
                if self.upstream_ws is not None:
                    with suppress(Exception):
                        await self.upstream_ws.close()
                self.upstream_ws = None
                await asyncio.sleep(1)

    async def handle_client(self, ws: WebSocketServerProtocol, path: str) -> None:
        """Handle a local client connection."""
        self.clients.add(ws)
        print(f"[relay] client connected ({len(self.clients)} total)")
        try:
            if self.bidirectional:
                # Forward client messages to upstream
                async for message in ws:
                    # Ensure upstream is connected
                    async with self.upstream_lock:
                        if self.upstream_ws is None or self.upstream_ws.closed:
                            await self.connect_upstream()
                    try:
                        print(f"[relay] forwarding message to upstream: {message}")  # Print message before sending to upstream
                        await self.upstream_ws.send(message)  # type: ignore
                    except Exception as e:
                        print(f"[relay] forward to upstream failed: {e}")
            else:
                # Keep the connection open; ignore client->server messages
                async for _ in ws:
                    pass
        finally:
            self.clients.discard(ws)
            print(f"[relay] client disconnected ({len(self.clients)} total)")

    async def run(self) -> None:
        # graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with suppress(NotImplementedError):
                loop.add_signal_handler(sig, self.stop_event.set)

        # start local websocket server
        self.server = await websockets.serve(
            self.handle_client,
            self.local_host,
            self.local_port,
            ping_interval=self.ping_interval,
            ping_timeout=self.ping_timeout,
        )
        print(f"[relay] local relay listening on ws://{self.local_host}:{self.local_port}")

        # start upstream reader
        self.reader_task = asyncio.create_task(self.upstream_reader())

        # wait for stop signal
        await self.stop_event.wait()
        print("[relay] shutting down...")

        # cleanup
        if self.reader_task:
            self.reader_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.reader_task
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        # close all clients
        for ws in list(self.clients):
            with suppress(Exception):
                await ws.close()
        # close upstream
        if self.upstream_ws is not None:
            with suppress(Exception):
                await self.upstream_ws.close()

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WebSocket relay")
    parser.add_argument(
        "--upstream",
        default="ws://10.10.0.3:8003/ws",
        help="Upstream WebSocket URI (default: ws://10.10.0.3:8003/ws)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Local host to bind (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8004,
        help="Local port to listen (default: 8004)",
    )
    parser.add_argument(
        "--bidirectional",
        action="store_true",
        help="Forward client messages to upstream as well",
    )
    return parser.parse_args()

async def async_main() -> None:
    args = parse_args()
    relay = Relay(
        upstream_uri=args.upstream,
        local_host=args.host,
        local_port=args.port,
        bidirectional=args.bidirectional,
    )
    await relay.run()

if __name__ == "__main__":
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        sys.exit(0)


