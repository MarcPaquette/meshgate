"""Tests that the server records transcripts through the real message path.

The recorder is wired into HandlerServer._handle_message, which is the only
place both the inbound text and the outbound response are in scope.
"""

import asyncio

import pytest

from meshgate.config import Config
from meshgate.core.transcript import Direction
from meshgate.server import HandlerServer
from tests.conftest import running_server
from tests.mocks import MockTransport


def make_server(*, transcript: bool = True, **web_overrides) -> tuple[HandlerServer, MockTransport]:
    """Build a server with transcripts configured."""
    config = Config.default()
    config.web.transcript_enabled = transcript
    for key, value in web_overrides.items():
        setattr(config.web, key, value)

    transport = MockTransport()
    return HandlerServer(config=config, transport=transport), transport


class TestRecordingThroughTheServer:
    """Both directions are captured for a real exchange."""

    async def test_records_inbound_and_outbound(self) -> None:
        server, transport = make_server()

        async with running_server(server):
            transport.inject_message("!menu", node_id="!node")
            await asyncio.sleep(0.3)

        entries = server.transcript.get("!node")

        assert [e.direction for e in entries] == [
            Direction.INBOUND,
            Direction.OUTBOUND,
        ]
        assert entries[0].text == "!menu"
        assert "Available Services" in entries[1].text

    async def test_records_a_multi_turn_exchange(self) -> None:
        server, transport = make_server()

        async with running_server(server):
            transport.inject_message("4", node_id="!node")  # enter Wikipedia
            await asyncio.sleep(0.2)
            transport.inject_message("!exit", node_id="!node")
            await asyncio.sleep(0.2)

        texts = [e.text for e in server.transcript.get("!node")]

        assert texts[0] == "4"
        assert texts[2] == "!exit"

    async def test_nodes_are_kept_separate(self) -> None:
        server, transport = make_server()

        async with running_server(server):
            transport.inject_message("!menu", node_id="!alice")
            transport.inject_message("!menu", node_id="!bob")
            await asyncio.sleep(0.4)

        assert server.transcript.get("!alice")
        assert server.transcript.get("!bob")
        assert set(server.transcript.node_ids()) == {"!alice", "!bob"}

    async def test_disabled_records_nothing(self) -> None:
        server, transport = make_server(transcript=False)

        async with running_server(server):
            transport.inject_message("!menu", node_id="!node")
            await asyncio.sleep(0.3)

        assert server.transcript.get("!node") == []
        assert server.transcript.enabled is False


class TestRateLimitExclusion:
    """Rejected floods must not fill the transcript with unacted-on messages."""

    async def test_rate_limited_messages_are_not_recorded(self) -> None:
        config = Config.default()
        config.web.transcript_enabled = True
        config.security.rate_limit_enabled = True
        config.security.rate_limit_messages = 1
        config.security.rate_limit_window_seconds = 60

        transport = MockTransport()
        server = HandlerServer(config=config, transport=transport)

        async with running_server(server):
            for _ in range(6):
                transport.inject_message("!menu", node_id="!spammer")
            await asyncio.sleep(0.5)

        inbound = [e for e in server.transcript.get("!spammer") if e.direction == Direction.INBOUND]

        # Only the one message that was actually allowed through.
        assert len(inbound) == 1


class TestPruning:
    """The periodic cleanup drops transcripts for sessions that are gone."""

    async def test_stale_transcripts_pruned_with_sessions(self) -> None:
        server, transport = make_server()

        async with running_server(server):
            transport.inject_message("!menu", node_id="!node")
            await asyncio.sleep(0.3)

            assert server.transcript.get("!node")

            # Session disappears (expiry or eviction), leaving a stale transcript.
            server.session_manager.remove_session("!node")
            live = {s.node_id for s in server.session_manager.list_sessions()}
            dropped = server.transcript.retain_only(live)

        assert dropped == 1
        assert server.transcript.get("!node") == []


class TestConfigWiring:
    """Limits come from config."""

    def test_limits_are_applied(self) -> None:
        server, _ = make_server(transcript_max_messages=7)

        assert server.transcript.max_messages == 7

    def test_recorder_disabled_by_default(self) -> None:
        server = HandlerServer(config=Config.default(), transport=MockTransport())

        assert server.transcript.enabled is False

    def test_invalid_limits_rejected_at_load(self) -> None:
        with pytest.raises(ValueError, match="transcript_max_messages must be positive"):
            Config.from_dict({"web": {"transcript_max_messages": 0}})

    def test_invalid_port_rejected_at_load(self) -> None:
        with pytest.raises(ValueError, match="web.port must be 1-65535"):
            Config.from_dict({"web": {"port": 0}})

    def test_invalid_log_buffer_rejected_at_load(self) -> None:
        with pytest.raises(ValueError, match="log_buffer_size must be positive"):
            Config.from_dict({"web": {"log_buffer_size": -1}})

    def test_web_defaults(self) -> None:
        web = Config.default().web

        assert web.enabled is False
        assert web.host == "127.0.0.1"
        assert web.transcript_enabled is False
