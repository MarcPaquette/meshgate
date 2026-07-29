# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build and Development Commands

```bash
uv sync                          # Install dependencies
uv sync --extra dev              # Install with dev dependencies
uv run pytest tests/ -v          # Run all tests
uv run pytest tests/path/test_file.py::TestClass::test_method -v  # Run single test
uv run ruff check src/ tests/    # Lint code
uv run ruff check src/ tests/ --fix  # Auto-fix lint issues
uv run ruff format src/ tests/   # Format code
uv run ruff format --check src/ tests/  # Verify formatting (CI gate)
uv run pytest tests/ --cov=src/meshgate --cov-report=term-missing  # Coverage
uv run python -m meshgate  # Run server
```

**Before pushing**, run the same three gates CI does (`.github/workflows/ci.yml`,
matrix: Python 3.11 and 3.12) — `ruff format --check` is easy to miss and fails
the build on its own:

```bash
uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run pytest tests/ -v
```

## Architecture Overview

Meshgate is a gateway server for Meshtastic mesh networks with a **plugin architecture**. Users connect via Meshtastic devices and interact through a numbered menu system.

### Message Flow

```
IncomingMessage → HandlerServer → MessageRouter → Plugin.handle()
                       ↓                              ↓
              SessionManager            PluginResponse (with state)
                       ↓                              ↓
              ContentChunker ← ← ← ← ← ← ← ← ← ← ← ←
                       ↓
              MeshtasticTransport.send_message()
```

### Core Components

**HandlerServer** (`server.py`) - Orchestrates all components:
- Owns the `PluginRegistry`, `SessionManager`, `MessageRouter`, `ContentChunker`
- Accepts custom `MessageTransport` for testing (inject `MockTransport`)
- Use `handle_single_message()` for testing without transport

### Concurrency Model

Messages are handled **concurrently across nodes but serialized per node**, so a
slow plugin call (e.g. a 30s LLM request) cannot stall the rest of the mesh:

- `_dispatch()` spawns a task per message, tracked in `_inflight` (strong refs —
  asyncio only holds weak ones)
- A global `asyncio.Semaphore` caps total in-flight handlers
- A per-node `asyncio.Lock` keeps one node's messages ordered. **This is
  required**: `Session` is a mutable dataclass with no locking, so overlapping
  messages from one node would corrupt `plugin_state`
- `stop()` waits `SHUTDOWN_GRACE_SECONDS` for in-flight work before cancelling,
  so multi-chunk replies aren't truncated

`MeshtasticTransport._on_receive` runs on **meshtastic's publishing thread**, not
the event loop. `asyncio.Queue` is not thread-safe, so it hands messages over via
`loop.call_soon_threadsafe()`. Radio sends use a dedicated single-thread executor
so concurrent handlers can't interleave writes on the serial stream.

**MessageRouter** (`core/message_router.py`) - Routes messages based on session state:
- At menu: number → enters plugin, shows welcome
- In plugin: message → `plugin.handle()`
- Universal commands (`!exit`, `!menu`, `!help`) intercepted before plugin

**Session** (`core/session.py`) - Per-node state (mutable dataclass):
- `active_plugin`: which plugin the node is in (None = at menu)
- `plugin_state`: dict passed to `plugin.handle()`, updated via `PluginResponse.plugin_state`
- Each Meshtastic node ID gets independent session

**Plugin Interface** (`interfaces/plugin.py`) - ABC for plugins:
- `metadata` property → `PluginMetadata(name, description, menu_number, commands)`
- `handle(message, context, plugin_state)` → `PluginResponse(message, plugin_state, exit_plugin)`
- Plugins are async, use `httpx` for HTTP calls
- `HTTPPluginBase` (`plugins/base.py`) - base class for HTTP plugins with error handling
- `PluginLoader` (`core/plugin_loader.py`) - dynamic plugin discovery from modules/files/dirs

**PluginRegistry** key methods: `register()`, `get_by_name()`, `get_by_menu_number()`, `get_all_plugins()`, `unregister()`

### Plugin State Pattern

Plugins are stateless between calls. State persists via `plugin_state` dict:

```python
async def handle(self, message, context, plugin_state):
    history = plugin_state.get("history", [])
    # ... process ...
    return PluginResponse(
        message="response",
        plugin_state={"history": new_history}  # Merged into session
    )
```

### Testing

- Use `MockTransport` and `MockPlugin` from `tests/mocks.py`
- HTTP calls mocked with `@respx.mock` decorator
- Fixtures in `tests/conftest.py`: `node_context`, `session`, `plugin_registry`, etc.

## Key Constraints

- **200 char message limit**: `ContentChunker` splits responses, adds `[...]` markers
- **Async plugins**: All `handle()` methods are async
- **Frozen dataclasses** for immutable data: `PluginMetadata`, `PluginResponse`, `NodeContext`, `GPSLocation`
- **Mutable Session**: Session tracks state, modified via methods not direct assignment

## Gotchas

- Wikipedia API returns 403 without a `User-Agent` header — always set one on `httpx.AsyncClient`
- `MeshtasticTransport` supports serial, tcp, and ble — BLE requires `meshtastic.ble_interface`
- `PluginRegistry.get_all_plugins()` (not `get_all()`) returns sorted plugin list

## Issue Tracking

Use GitHub issues. See AGENTS.md for the session workflow.
