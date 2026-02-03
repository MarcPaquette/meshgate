# Meshgate

A gateway server for Meshtastic mesh networks with a plugin architecture. Provides an interactive menu system for users to access various services over the mesh.

## Features

- **Plugin Architecture**: Easily extensible with custom plugins
- **Per-Node Sessions**: Each Meshtastic node gets independent session state
- **Built-in Plugins**:
  - **Gopher Server**: Browse files and directories
  - **LLM Assistant**: AI-powered chat using Ollama
  - **Weather**: GPS-based weather from Open-Meteo
  - **Wikipedia**: Search and read Wikipedia articles
- **Message Chunking**: Automatic splitting of long responses for radio limits
- **Multiple Connection Types**: Serial, TCP, and BLE support
- **Security Features** (all opt-in):
  - **Node Filtering**: Allowlist/denylist for access control
  - **Rate Limiting**: Per-node message throttling
  - **Session Management**: Automatic cleanup and limits

## Installation

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/) package manager.

```bash
# Clone the repository
git clone https://github.com/MarcPaquette/meshgate.git
cd meshgate

# Install dependencies
uv sync

# Install with dev dependencies (for testing)
uv sync --extra dev
```

## Quick Start

```bash
# Run with auto-detect serial device
uv run python -m meshgate

# Run with specific serial device
uv run python -m meshgate --device /dev/ttyUSB0

# Run with TCP connection
uv run python -m meshgate --connection tcp --tcp-host 192.168.1.100

# Run with config file
uv run python -m meshgate --config config.yaml
```

## User Interaction Flow

When a user sends any message to the server:

```
User sends any message
        ↓
┌─────────────────────────────┐
│     MAIN MENU               │
│  "Available Services:"      │
│  1. Gopher Server           │
│  2. LLM Assistant           │
│  3. Weather                 │
│  4. Wikipedia               │
│                             │
│  Send number to select      │
└─────────────────────────────┘
        ↓
User sends "2"
        ↓
┌─────────────────────────────┐
│     LLM PLUGIN ACTIVE       │
│  "LLM Assistant"            │
│  Send your question or:     │
│  !help - show commands      │
│  !exit - return to menu     │
└─────────────────────────────┘
```

### Universal Commands

These commands work anywhere:
- `!exit` - Return to main menu
- `!menu` - Show main menu
- `!help` - Show plugin-specific help (when in a plugin)

## Configuration

Copy `config.sample.yaml` to `config.yaml` and customize:

```yaml
server:
  max_message_size: 200
  session_timeout_minutes: 60
  session_cleanup_interval_minutes: 5  # How often to clean expired sessions
  max_sessions: 0                      # 0 = unlimited

meshtastic:
  connection_type: serial  # serial, tcp, or ble
  device: null             # auto-detect

plugins:
  llm:
    ollama_url: "http://localhost:11434"
    model: "llama3.2"
  weather:
    timeout: 10.0
  wikipedia:
    language: "en"

security:
  # Node filtering (disabled by default)
  node_allowlist: []         # Empty = allow all
  node_denylist: []          # Always blocks these nodes
  require_allowlist: false   # If true, only allowlisted nodes connect

  # Rate limiting (disabled by default)
  rate_limit_enabled: false
  rate_limit_messages: 10    # Max messages per window
  rate_limit_window_seconds: 60
```

## Built-in Plugins

### 1. Gopher Server (Menu #1)

Browse files and directories on the server.

Commands:
- `[number]` - Select item
- `!back` - Go to parent directory
- `!home` - Return to root directory

### 2. LLM Assistant (Menu #2)

Chat with an AI using Ollama.

Commands:
- `[message]` - Ask a question
- `!model <name>` - Switch model
- `!models` - List available models
- `!clear` - Clear conversation history

Requires [Ollama](https://ollama.ai/) running locally.

### 3. Weather (Menu #3)

Get weather for your GPS location.

Commands:
- `!refresh` - Get current weather
- `!forecast` - Get 3-day forecast

Requires GPS enabled on your Meshtastic device.

### 4. Wikipedia (Menu #4)

Search and read Wikipedia articles.

Commands:
- `[topic]` - Search for topic
- `!search <query>` - Search Wikipedia
- `!random` - Get random article

## Security

All security features are **opt-in** and disabled by default for backwards compatibility.

### Node Filtering

Control which nodes can connect to your server:

```yaml
security:
  node_allowlist: ["!abc123", "!def456"]  # Only these nodes allowed
  node_denylist: ["!spammer"]             # Always blocked
  require_allowlist: true                  # Enforce allowlist
```

- **Denylist** always takes precedence (checked first)
- **Allowlist** only enforced when `require_allowlist: true`
- Empty lists with `require_allowlist: false` allows all nodes

### Rate Limiting

Prevent message flooding with per-node rate limits:

```yaml
security:
  rate_limit_enabled: true
  rate_limit_messages: 10      # Max 10 messages
  rate_limit_window_seconds: 60  # Per 60 second window
```

Uses a sliding window algorithm. Blocked nodes receive a "Rate limited. Try in Xs" response.

### Session Management

Prevent memory exhaustion from abandoned sessions:

```yaml
server:
  session_timeout_minutes: 60        # Expire inactive sessions
  session_cleanup_interval_minutes: 5  # Cleanup frequency
  max_sessions: 1000                 # Limit concurrent sessions (0 = unlimited)
```

When `max_sessions` is reached, the oldest (least recently active) session is evicted.

## Development

### Running Tests

```bash
uv run pytest tests/ -v
```

### Project Structure

```
meshgate/
├── src/meshgate/
│   ├── interfaces/          # Abstract base classes (Plugin, MessageTransport)
│   ├── core/                # Plugin registry, routing, sessions, plugin loader
│   ├── transport/           # Meshtastic transport implementation
│   └── plugins/             # Built-in plugins and base classes
├── tests/                   # Test suite
└── config.sample.yaml       # Example configuration
```

### Creating Custom Plugins

#### Basic Plugin

```python
from meshgate.interfaces.plugin import Plugin, PluginMetadata, PluginResponse
from meshgate.interfaces.node_context import NodeContext

class MyPlugin(Plugin):
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="My Plugin",
            description="Does something cool",
            menu_number=5,
            commands=("!do", "!undo")
        )

    def get_welcome_message(self) -> str:
        return "Welcome to My Plugin!\nSend !help for commands."

    def get_help_text(self) -> str:
        return "Commands:\n!do - Do it\n!undo - Undo it\n!exit - Return to menu"

    async def handle(self, message: str, context: NodeContext, plugin_state: dict) -> PluginResponse:
        if message == "!do":
            return PluginResponse(message="Done!")
        return PluginResponse(message="Unknown command")
```

#### Plugin State Management

Plugins are stateless between calls. Use `plugin_state` to persist data:

```python
async def handle(self, message: str, context: NodeContext, plugin_state: dict) -> PluginResponse:
    # Read state from previous calls
    history = plugin_state.get("history", [])
    history.append(message)

    # Return updated state
    return PluginResponse(
        message=f"You've sent {len(history)} messages",
        plugin_state={"history": history}  # State persists to next call
    )
```

#### HTTP Plugins

For plugins that make HTTP requests, inherit from `HTTPPluginBase` for built-in error handling:

```python
from meshgate.plugins.base import HTTPPluginBase
from meshgate.interfaces.plugin import PluginMetadata, PluginResponse
from meshgate.interfaces.node_context import NodeContext

class MyAPIPlugin(HTTPPluginBase):
    def __init__(self):
        super().__init__(timeout=10.0, service_name="My API")

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(name="My API", description="Fetches data", menu_number=5)

    def get_welcome_message(self) -> str:
        return "My API Plugin"

    def get_help_text(self) -> str:
        return "Send a query to fetch data"

    async def handle(self, message: str, context: NodeContext, plugin_state: dict) -> PluginResponse:
        # _fetch_json handles errors and returns PluginResponse on failure
        data = await self._fetch_json(
            "https://api.example.com/data",
            params={"query": message}
        )
        if isinstance(data, PluginResponse):
            return data  # Error occurred, return error response

        return PluginResponse(message=data.get("result", "No result"))
```

#### Dynamic Plugin Loading

**Security Warning**: External plugins execute arbitrary Python code with full system access. This feature is disabled by default. Only enable for trusted plugins.

Load plugins dynamically from modules or files:

```python
from meshgate.core.plugin_loader import PluginLoader

loader = PluginLoader()

# Load from installed module
plugin = loader.load_plugin("my_package.plugins.custom")

# Load from file
plugin = loader.load_plugin_from_file("/path/to/my_plugin.py")

# Discover all plugins in a directory
plugins = loader.discover_plugins("/path/to/plugins/")
```

## License

MIT
