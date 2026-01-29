"""Node context dataclasses for plugin message handling."""

from dataclasses import dataclass


@dataclass(frozen=True)
class GPSLocation:
    """GPS location data from a Meshtastic node.

    Attributes:
        latitude: Latitude in decimal degrees (-90 to 90)
        longitude: Longitude in decimal degrees (-180 to 180)
        altitude: Altitude in meters above sea level (optional)
    """

    latitude: float
    longitude: float
    altitude: float | None = None

    def __post_init__(self) -> None:
        """Validate coordinate ranges."""
        if not -90 <= self.latitude <= 90:
            raise ValueError(f"Latitude must be between -90 and 90, got {self.latitude}")
        if not -180 <= self.longitude <= 180:
            raise ValueError(f"Longitude must be between -180 and 180, got {self.longitude}")


@dataclass(frozen=True)
class NodeContext:
    """Context information about a Meshtastic node sending a message.

    Provides plugins with node information for personalizing responses.

    Attributes:
        node_id: Unique Meshtastic node identifier (e.g., "!abc12345")
        node_name: Human-readable display name (optional)
        location: GPS coordinates if available (optional)
    """

    node_id: str
    node_name: str | None = None
    location: GPSLocation | None = None

    def __post_init__(self) -> None:
        """Validate node_id format."""
        if not self.node_id:
            raise ValueError("node_id cannot be empty")
