"""Content chunker for splitting messages to fit radio limits."""


class ContentChunker:
    """Splits long messages into chunks that fit within Meshtastic limits.

    Meshtastic has a maximum message size (typically ~200 characters for
    encrypted messages). This class splits longer messages intelligently,
    preferring to break at word boundaries.
    """

    # Continuation markers
    MORE_MARKER = " [...]"
    CONT_MARKER = "[...] "

    def __init__(self, max_size: int = 200) -> None:
        """Initialize the content chunker.

        Args:
            max_size: Maximum characters per chunk (default 200)
        """
        if max_size < 20:
            raise ValueError(f"max_size must be at least 20, got {max_size}")
        self._max_size = max_size

    def chunk(self, text: str) -> list[str]:
        """Split text into chunks that fit within the size limit.

        Args:
            text: The text to split

        Returns:
            List of text chunks
        """
        if not text:
            return []

        text = text.strip()
        if not text:
            return []
        if len(text) <= self._max_size:
            return [text]

        chunks = []
        remaining = text

        while remaining:
            if len(remaining) <= self._max_size:
                # Last chunk - no continuation needed if first chunk
                if chunks:
                    chunks.append(self.CONT_MARKER + remaining)
                else:
                    chunks.append(remaining)
                break

            # Need to split - account for markers
            if chunks:
                # Not first chunk - need both markers
                available = self._max_size - len(self.CONT_MARKER) - len(self.MORE_MARKER)
            else:
                # First chunk - only need more marker
                available = self._max_size - len(self.MORE_MARKER)

            # Find a good break point (prefer word boundaries)
            break_point = self._find_break_point(remaining, available)

            # Create chunk
            chunk_text = remaining[:break_point].rstrip()
            if chunks:
                chunk_text = self.CONT_MARKER + chunk_text
            chunk_text = chunk_text + self.MORE_MARKER

            chunks.append(chunk_text)
            remaining = remaining[break_point:].lstrip()

        return chunks

    def _find_break_point(self, text: str, max_length: int) -> int:
        """Find the best position to break text.

        Prefers to break at:
        1. Paragraph breaks (double newline)
        2. Sentence endings (. ! ?)
        3. Clause breaks (, ; :)
        4. Word boundaries (space)
        5. Any position (as last resort)

        Args:
            text: The text to analyze
            max_length: Maximum length before break

        Returns:
            Position to break at
        """
        if len(text) <= max_length:
            return len(text)

        # Look for break points, starting from best to worst
        search_region = text[:max_length]

        # Try paragraph break first
        para_break = search_region.rfind("\n\n")
        if para_break > max_length // 2:
            return para_break + 2

        # Try sentence ending
        for punct in ".!?":
            pos = search_region.rfind(punct + " ")
            if pos > max_length // 2:
                return pos + 2
            # Also try at end of search region
            if search_region.endswith(punct):
                return max_length

        # Try newline
        newline = search_region.rfind("\n")
        if newline > max_length // 2:
            return newline + 1

        # Try clause break
        for punct in ",;:":
            pos = search_region.rfind(punct + " ")
            if pos > max_length // 2:
                return pos + 2

        # Try word boundary
        space = search_region.rfind(" ")
        if space > max_length // 3:
            return space + 1

        # Last resort - just cut at max length
        return max_length

    @property
    def max_size(self) -> int:
        """Get the maximum chunk size."""
        return self._max_size
