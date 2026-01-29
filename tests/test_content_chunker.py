"""Tests for content chunker."""

import pytest

from meshgate.core.content_chunker import ContentChunker


class TestContentChunker:
    """Tests for ContentChunker class."""

    def test_short_message_unchanged(self) -> None:
        """Test that short messages are not chunked."""
        chunker = ContentChunker(max_size=200)
        text = "Hello, world!"

        chunks = chunker.chunk(text)

        assert len(chunks) == 1
        assert chunks[0] == "Hello, world!"

    def test_empty_message(self) -> None:
        """Test empty message returns empty list."""
        chunker = ContentChunker(max_size=200)

        chunks = chunker.chunk("")

        assert chunks == []

    def test_whitespace_only(self) -> None:
        """Test whitespace-only message returns empty list."""
        chunker = ContentChunker(max_size=200)

        chunks = chunker.chunk("   \n\t  ")

        assert chunks == []

    def test_exact_size_message(self) -> None:
        """Test message exactly at max size."""
        chunker = ContentChunker(max_size=50)
        text = "x" * 50

        chunks = chunker.chunk(text)

        assert len(chunks) == 1

    def test_message_split_into_chunks(self) -> None:
        """Test long message is split into multiple chunks."""
        chunker = ContentChunker(max_size=50)
        text = "x" * 150

        chunks = chunker.chunk(text)

        assert len(chunks) > 1
        # Each chunk should be <= max_size
        for chunk in chunks:
            assert len(chunk) <= 50

    def test_continuation_markers(self) -> None:
        """Test that chunks have continuation markers."""
        chunker = ContentChunker(max_size=50)
        text = "x" * 150

        chunks = chunker.chunk(text)

        # First chunk should end with [...]
        assert chunks[0].endswith("[...]")
        # Middle chunks should have both markers
        if len(chunks) > 2:
            assert chunks[1].startswith("[...]")
            assert chunks[1].endswith("[...]")
        # Last chunk should start with [...]
        assert chunks[-1].startswith("[...]")

    def test_word_boundary_break(self) -> None:
        """Test chunker prefers word boundaries."""
        chunker = ContentChunker(max_size=50)
        text = "The quick brown fox jumps over the lazy dog and more text here"

        chunks = chunker.chunk(text)

        # Multiple chunks should be created
        assert len(chunks) >= 2

        # Each chunk should not break in the middle of a word
        # (i.e., no chunks should end with a partial word followed by [...]
        # where the partial would be completed in the next chunk)
        for i, chunk in enumerate(chunks[:-1]):
            # Remove markers and get clean text
            clean = chunk.replace("[...]", "").strip()
            # Words in the original text
            words = text.split()
            # The clean text should end with a complete word from the original
            if clean:
                last_word = clean.split()[-1] if clean.split() else ""
                assert last_word in words or not last_word

    def test_sentence_boundary_break(self) -> None:
        """Test chunker prefers sentence boundaries."""
        chunker = ContentChunker(max_size=100)
        text = "First sentence here. Second sentence here. Third sentence here. Fourth sentence."

        chunks = chunker.chunk(text)

        # Check that breaks happen at sentence boundaries when possible
        for chunk in chunks[:-1]:
            clean = chunk.replace("[...]", "").strip()
            # Should end with sentence punctuation when possible
            if len(clean) > 50:
                assert any(clean.endswith(p) for p in (".", "!", "?", " "))

    def test_invalid_max_size(self) -> None:
        """Test that invalid max_size raises error."""
        with pytest.raises(ValueError, match="max_size must be at least"):
            ContentChunker(max_size=10)

    def test_max_size_property(self) -> None:
        """Test max_size property."""
        chunker = ContentChunker(max_size=150)
        assert chunker.max_size == 150

    def test_newline_preserved_in_chunks(self) -> None:
        """Test that meaningful content is preserved across chunks."""
        chunker = ContentChunker(max_size=100)
        text = "Line 1\nLine 2\nLine 3\n" * 10

        chunks = chunker.chunk(text)

        # Reassemble and check content is preserved
        reassembled = ""
        for chunk in chunks:
            clean = chunk.replace("[...]", "").strip()
            reassembled += clean + " "

        assert "Line 1" in reassembled
        assert "Line 2" in reassembled

    def test_unicode_content(self) -> None:
        """Test handling of unicode content."""
        chunker = ContentChunker(max_size=50)
        text = "Hello " + "日本語" * 30

        chunks = chunker.chunk(text)

        assert len(chunks) > 0
        # Should not crash
        for chunk in chunks:
            assert len(chunk) <= 50

    def test_single_word_exceeding_max_size(self) -> None:
        """Test chunking when a single word exceeds max_size."""
        chunker = ContentChunker(max_size=30)
        # A very long word that can't fit in one chunk
        text = "a" * 60

        chunks = chunker.chunk(text)

        # Should still produce valid chunks
        assert len(chunks) > 0
        for chunk in chunks:
            assert len(chunk) <= 30

    def test_long_word_with_surrounding_text(self) -> None:
        """Test chunking with long word surrounded by normal text."""
        chunker = ContentChunker(max_size=50)
        text = f"Start {'x' * 80} end"

        chunks = chunker.chunk(text)

        # Should produce chunks without crashing
        assert len(chunks) > 0
        # Content should be preserved
        combined = " ".join(c.replace("[...]", "") for c in chunks)
        assert "Start" in combined
        assert "end" in combined

    def test_only_continuation_marker_fits(self) -> None:
        """Test edge case where chunk needs continuation markers."""
        chunker = ContentChunker(max_size=30)  # minimum is 20
        text = "word " * 20

        chunks = chunker.chunk(text)

        # All chunks should fit
        for chunk in chunks:
            assert len(chunk) <= 30

    def test_reassembled_content_complete(self) -> None:
        """Test that reassembled chunks contain all original words."""
        chunker = ContentChunker(max_size=50)
        text = "The quick brown fox jumps over the lazy dog repeatedly many times"

        chunks = chunker.chunk(text)

        # Reassemble without markers
        reassembled = ""
        for chunk in chunks:
            clean = chunk.replace("[...]", " ").strip()
            reassembled += clean + " "

        # All words should be present
        for word in text.split():
            assert word in reassembled
