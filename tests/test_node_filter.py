"""Tests for node filtering."""

from meshgate.core.node_filter import NodeFilter


class TestNodeFilter:
    """Tests for NodeFilter class."""

    def test_allow_all_by_default(self) -> None:
        """Test that empty filter allows all nodes."""
        node_filter = NodeFilter()

        assert node_filter.is_allowed("!node1")
        assert node_filter.is_allowed("!node2")
        assert node_filter.is_allowed("!anynode")

    def test_denylist_blocks_nodes(self) -> None:
        """Test that denylist blocks specified nodes."""
        node_filter = NodeFilter(denylist=["!blocked1", "!blocked2"])

        assert not node_filter.is_allowed("!blocked1")
        assert not node_filter.is_allowed("!blocked2")
        assert node_filter.is_allowed("!allowed")

    def test_allowlist_without_require_allows_all(self) -> None:
        """Test that allowlist without require_allowlist allows all nodes."""
        node_filter = NodeFilter(allowlist=["!allowed1"], require_allowlist=False)

        assert node_filter.is_allowed("!allowed1")
        assert node_filter.is_allowed("!other")

    def test_require_allowlist_restricts_access(self) -> None:
        """Test that require_allowlist only allows listed nodes."""
        node_filter = NodeFilter(
            allowlist=["!allowed1", "!allowed2"], require_allowlist=True
        )

        assert node_filter.is_allowed("!allowed1")
        assert node_filter.is_allowed("!allowed2")
        assert not node_filter.is_allowed("!other")

    def test_denylist_takes_precedence(self) -> None:
        """Test that denylist blocks even if in allowlist."""
        node_filter = NodeFilter(
            allowlist=["!node1"],
            denylist=["!node1"],
            require_allowlist=True,
        )

        # Denylist takes precedence
        assert not node_filter.is_allowed("!node1")

    def test_empty_allowlist_with_require_blocks_all(self) -> None:
        """Test that empty allowlist with require_allowlist blocks all."""
        node_filter = NodeFilter(allowlist=[], require_allowlist=True)

        assert not node_filter.is_allowed("!node1")
        assert not node_filter.is_allowed("!node2")

    def test_properties(self) -> None:
        """Test filter properties."""
        node_filter = NodeFilter(
            allowlist=["!a", "!b"],
            denylist=["!c"],
            require_allowlist=True,
        )

        assert node_filter.allowlist == {"!a", "!b"}
        assert node_filter.denylist == {"!c"}
        assert node_filter.require_allowlist is True

    def test_properties_return_copies(self) -> None:
        """Test that properties return copies, not originals."""
        node_filter = NodeFilter(allowlist=["!a"])

        allowlist = node_filter.allowlist
        allowlist.add("!b")

        # Original should be unchanged
        assert node_filter.allowlist == {"!a"}

    def test_none_lists_treated_as_empty(self) -> None:
        """Test that None lists are treated as empty."""
        node_filter = NodeFilter(allowlist=None, denylist=None)

        assert node_filter.allowlist == set()
        assert node_filter.denylist == set()
        assert node_filter.is_allowed("!any")


class TestNodeFilterIntegration:
    """Integration tests for node filtering scenarios."""

    def test_typical_denylist_usage(self) -> None:
        """Test typical usage: denylist only, block known bad actors."""
        node_filter = NodeFilter(denylist=["!spammer", "!abuser"])

        # Normal nodes allowed
        assert node_filter.is_allowed("!friend1")
        assert node_filter.is_allowed("!friend2")

        # Bad actors blocked
        assert not node_filter.is_allowed("!spammer")
        assert not node_filter.is_allowed("!abuser")

    def test_typical_allowlist_usage(self) -> None:
        """Test typical usage: allowlist for private network."""
        node_filter = NodeFilter(
            allowlist=["!mynode", "!friendnode"],
            require_allowlist=True,
        )

        # Only allowed nodes can connect
        assert node_filter.is_allowed("!mynode")
        assert node_filter.is_allowed("!friendnode")
        assert not node_filter.is_allowed("!stranger")

    def test_combined_usage(self) -> None:
        """Test combined allowlist and denylist."""
        node_filter = NodeFilter(
            allowlist=["!trusted1", "!trusted2", "!probation"],
            denylist=["!probation"],  # On probation, currently blocked
            require_allowlist=True,
        )

        assert node_filter.is_allowed("!trusted1")
        assert node_filter.is_allowed("!trusted2")
        assert not node_filter.is_allowed("!probation")  # Denylist wins
        assert not node_filter.is_allowed("!random")
