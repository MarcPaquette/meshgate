"""Command-line interface for Meshtastic Handler Server."""

import argparse
import asyncio
import logging
import signal
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
    # force=True: basicConfig is a no-op if anything already configured the
    # root logger, which would silently make -v do nothing.
    logging.basicConfig(level=level, format=format_str, force=True)


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
        # No exists() pre-check: it would double-stat and leave a window where
        # the file can vanish, turning a clean exit into a traceback.
        try:
            config = Config.from_yaml(Path(args.config))
        except FileNotFoundError:
            print(f"Error: Configuration file not found: {args.config}", file=sys.stderr)
            sys.exit(1)
        except (ValueError, OSError) as e:
            print(f"Error: Invalid configuration: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # Check for default config locations
        default_paths = [
            Path("config.yaml"),
            Path("config.yml"),
            Path.home() / ".config" / "meshtastic-handler" / "config.yaml",
        ]
        config = None
        for path in default_paths:
            try:
                config = Config.from_yaml(path)
                break
            except FileNotFoundError:
                continue
            except (ValueError, OSError) as e:
                print(f"Error: Invalid configuration in {path}: {e}", file=sys.stderr)
                sys.exit(1)
        if config is None:
            config = Config.default()

    # Apply CLI overrides. `is not None` rather than truthiness: argparse
    # defaults these to None, and --tcp-port 0 is a real (if unusual) value.
    if args.connection is not None:
        config.meshtastic.connection_type = args.connection
    if args.device is not None:
        config.meshtastic.device = args.device
    if args.tcp_host is not None:
        config.meshtastic.tcp_host = args.tcp_host
    if args.tcp_port is not None:
        config.meshtastic.tcp_port = args.tcp_port

    # Re-validate: overrides bypass the checks run at load time. Reported the
    # same way as a bad file, rather than as a traceback.
    try:
        config.validate()
    except ValueError as e:
        print(f"Error: Invalid configuration: {e}", file=sys.stderr)
        sys.exit(1)

    return config


async def run_server(config: Config) -> None:
    """Run the server with the given configuration.

    Args:
        config: Server configuration
    """
    server = HandlerServer(config=config)

    # Under systemd or Docker the process is stopped with SIGTERM, which would
    # otherwise kill it without ever closing the serial interface.
    loop = asyncio.get_running_loop()
    server_task = asyncio.ensure_future(server.start())
    for signame in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, signame, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, server_task.cancel)
        except NotImplementedError:
            # Not supported on this platform (e.g. Windows)
            pass

    try:
        await server_task
    except (KeyboardInterrupt, asyncio.CancelledError):
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
