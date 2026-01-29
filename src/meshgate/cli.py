"""Command-line interface for Meshtastic Handler Server."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from meshgate.config import Config
from meshgate.server import HandlerServer


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the application.

    Args:
        verbose: Enable debug logging if True
    """
    level = logging.DEBUG if verbose else logging.INFO
    format_str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=level, format=format_str)


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        args: Command-line arguments (defaults to sys.argv)

    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(
        prog="meshtastic-handler",
        description="Meshtastic Handler Server - Plugin-based message handler",
    )

    parser.add_argument(
        "-c",
        "--config",
        type=str,
        default=None,
        help="Path to configuration file (YAML)",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose/debug logging",
    )

    parser.add_argument(
        "--connection",
        type=str,
        choices=["serial", "tcp", "ble"],
        default=None,
        help="Connection type (overrides config)",
    )

    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="Serial device path (overrides config)",
    )

    parser.add_argument(
        "--tcp-host",
        type=str,
        default=None,
        help="TCP host address (overrides config)",
    )

    parser.add_argument(
        "--tcp-port",
        type=int,
        default=None,
        help="TCP port (overrides config)",
    )

    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.1.0",
    )

    return parser.parse_args(args)


def load_config(args: argparse.Namespace) -> Config:
    """Load configuration from file and apply CLI overrides.

    Args:
        args: Parsed command-line arguments

    Returns:
        Configuration object
    """
    # Load base configuration
    if args.config:
        config_path = Path(args.config)
        if not config_path.exists():
            print(f"Error: Configuration file not found: {config_path}", file=sys.stderr)
            sys.exit(1)
        config = Config.from_yaml(config_path)
    else:
        # Check for default config locations
        default_paths = [
            Path("config.yaml"),
            Path("config.yml"),
            Path.home() / ".config" / "meshtastic-handler" / "config.yaml",
        ]
        config = None
        for path in default_paths:
            if path.exists():
                config = Config.from_yaml(path)
                break
        if config is None:
            config = Config.default()

    # Apply CLI overrides
    if args.connection:
        config.meshtastic.connection_type = args.connection
    if args.device:
        config.meshtastic.device = args.device
    if args.tcp_host:
        config.meshtastic.tcp_host = args.tcp_host
    if args.tcp_port:
        config.meshtastic.tcp_port = args.tcp_port

    return config


async def run_server(config: Config) -> None:
    """Run the server with the given configuration.

    Args:
        config: Server configuration
    """
    server = HandlerServer(config=config)

    try:
        await server.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        logging.error(f"Server error: {e}")
        sys.exit(1)
    finally:
        await server.stop()


def main(args: list[str] | None = None) -> None:
    """Main entry point for the CLI.

    Args:
        args: Command-line arguments (defaults to sys.argv)
    """
    parsed_args = parse_args(args)
    setup_logging(verbose=parsed_args.verbose)

    config = load_config(parsed_args)

    try:
        asyncio.run(run_server(config))
    except KeyboardInterrupt:
        print("\nGoodbye!")


if __name__ == "__main__":
    main()
