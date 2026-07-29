"""Tests for runtime plugin enable/disable.

A disabled plugin must vanish from the menu and stop being routable, while
keeping its menu number reserved so nothing else can claim it and re-enabling
cannot collide.
"""

import pytest

from meshgate.config import Config
from meshgate.core.message_router import MessageRouter
from meshgate.core.plugin_registry import PluginRegistry
from meshgate.core.session import Session
from meshgate.interfaces.node_context import NodeContext
from meshgate.server import HandlerServer
from tests.mocks import MockPlugin, MockTransport


@pytest.fixture
def registry() -> PluginRegistry:
    """Registry with two plugins registered."""
    reg = PluginRegistry()
    reg.register(MockPlugin(name="Alpha", menu_number=1))
    reg.register(MockPlugin(name="Beta", menu_number=2))
    return reg


class TestDisableEnable:
    """Basic disable/enable mechanics."""

    def test_disable_removes_from_enabled_list(self, registry: PluginRegistry) -> None:
        assert registry.disable("Alpha") is True

        assert [p.metadata.name for p in registry.get_all_plugins()] == ["Beta"]
        assert registry.plugin_count == 1
        assert registry.disabled_count == 1

    def test_disabled_plugin_is_not_routable(self, registry: PluginRegistry) -> None:
        registry.disable("Alpha")

        assert registry.get_by_name("Alpha") is None
        assert registry.get_by_menu_number(1) is None
        assert "Alpha" not in registry

    def test_enable_restores_plugin(self, registry: PluginRegistry) -> None:
        registry.disable("Alpha")

        assert registry.enable("Alpha") is True

        assert [p.metadata.name for p in registry.get_all_plugins()] == ["Alpha", "Beta"]
        assert registry.get_by_menu_number(1).metadata.name == "Alpha"
        assert registry.disabled_count == 0

    def test_enable_returns_the_same_instance(self, registry: PluginRegistry) -> None:
        """Re-enabling must not reconstruct - construction can have side effects."""
        original = registry.get_by_name("Alpha")
        registry.disable("Alpha")
        registry.enable("Alpha")

        assert registry.get_by_name("Alpha") is original

    def test_disable_unknown_plugin(self, registry: PluginRegistry) -> None:
        assert registry.disable("Nope") is False

    def test_enable_plugin_that_is_not_disabled(self, registry: PluginRegistry) -> None:
        assert registry.enable("Alpha") is False

    def test_double_disable(self, registry: PluginRegistry) -> None:
        assert registry.disable("Alpha") is True
        assert registry.disable("Alpha") is False

    def test_is_disabled(self, registry: PluginRegistry) -> None:
        assert registry.is_disabled("Alpha") is False
        registry.disable("Alpha")
        assert registry.is_disabled("Alpha") is True


class TestMenuNumberReservation:
    """A disabled plugin keeps its slot so re-enabling can't collide."""

    def test_menu_number_stays_reserved(self, registry: PluginRegistry) -> None:
        registry.disable("Alpha")

        with pytest.raises(ValueError, match="Menu number 1 is already used"):
            registry.register(MockPlugin(name="Usurper", menu_number=1))

    def test_name_stays_reserved(self, registry: PluginRegistry) -> None:
        registry.disable("Alpha")

        with pytest.raises(ValueError, match="already registered"):
            registry.register(MockPlugin(name="Alpha", menu_number=9))

    def test_unregister_frees_a_disabled_plugin(self, registry: PluginRegistry) -> None:
        registry.disable("Alpha")

        assert registry.unregister("Alpha") is True

        assert registry.disabled_count == 0
        # Slot is now genuinely free.
        registry.register(MockPlugin(name="Replacement", menu_number=1))
        assert registry.get_by_menu_number(1).metadata.name == "Replacement"


class TestVersionAndCache:
    """Toggling must invalidate anything derived from the plugin set."""

    def test_version_changes_on_toggle(self, registry: PluginRegistry) -> None:
        before = registry.version
        registry.disable("Alpha")
        after_disable = registry.version
        registry.enable("Alpha")

        assert after_disable != before
        assert registry.version != after_disable

    def test_menu_reflects_disable_and_enable(self, registry: PluginRegistry) -> None:
        router = MessageRouter(registry)
        assert "Alpha" in router.get_menu()

        registry.disable("Alpha")
        assert "Alpha" not in router.get_menu()

        registry.enable("Alpha")
        assert "Alpha" in router.get_menu()

    def test_list_all_reports_both_states(self, registry: PluginRegistry) -> None:
        registry.disable("Alpha")

        listed = [(p.metadata.name, on) for p, on in registry.list_all()]

        assert listed == [("Alpha", False), ("Beta", True)]


class TestActiveSessionInDisabledPlugin:
    """A node inside a plugin that gets disabled must degrade gracefully."""

    async def test_session_returns_to_menu(self, registry: PluginRegistry) -> None:
        router = MessageRouter(registry)
        session = Session(node_id="!node")
        context = NodeContext(node_id="!node")

        # Enter Alpha, then disable it underneath the session.
        await router.route("1", session, context)
        assert session.active_plugin == "Alpha"

        registry.disable("Alpha")
        response = await router.route("hello", session, context)

        assert "not available" in response.message.lower()
        assert session.is_at_menu
        assert session.active_plugin is None


class TestConfigDrivenEnable:
    """config.plugins.<name>.enabled gates registration at startup."""

    def test_all_builtins_enabled_by_default(self) -> None:
        server = HandlerServer(config=Config.default(), transport=MockTransport())

        names = {p.metadata.name for p in server.registry.get_all_plugins()}

        assert names == {"Gopher Server", "LLM Assistant", "Weather", "Wikipedia"}
        assert server.registry.disabled_count == 0

    def test_disabled_plugin_is_registered_but_off(self) -> None:
        config = Config.default()
        config.plugins.weather.enabled = False

        server = HandlerServer(config=config, transport=MockTransport())

        assert server.registry.get_by_name("Weather") is None
        assert server.registry.is_disabled("Weather") is True
        assert "Weather" not in server.router.get_menu()

    def test_disabled_plugin_can_be_enabled_at_runtime(self) -> None:
        config = Config.default()
        config.plugins.weather.enabled = False
        server = HandlerServer(config=config, transport=MockTransport())

        assert server.registry.enable("Weather") is True

        assert server.registry.get_by_name("Weather") is not None
        assert "Weather" in server.router.get_menu()

    def test_menu_numbers_survive_a_disabled_plugin(self) -> None:
        """Disabling one plugin must not renumber the others."""
        config = Config.default()
        config.plugins.gopher.enabled = False
        server = HandlerServer(config=config, transport=MockTransport())

        assert server.registry.get_by_menu_number(1) is None
        assert server.registry.get_by_menu_number(3).metadata.name == "Weather"

    def test_all_plugins_disabled_yields_empty_menu(self) -> None:
        config = Config.default()
        for plugin_cfg in (
            config.plugins.gopher,
            config.plugins.llm,
            config.plugins.weather,
            config.plugins.wikipedia,
        ):
            plugin_cfg.enabled = False

        server = HandlerServer(config=config, transport=MockTransport())

        assert server.registry.plugin_count == 0
        assert server.registry.disabled_count == 4


class TestConstructorMapping:
    """Config fields must not be splatted blindly into plugin constructors."""

    def test_enabled_field_does_not_reach_constructors(self) -> None:
        """Regression: asdict() splatting passed `enabled` as an unexpected kwarg.

        Every plugin config now carries `enabled`, which is not a constructor
        parameter. Constructing the server proves the mapping is explicit.
        """
        config = Config.default()

        server = HandlerServer(config=config, transport=MockTransport())

        assert server.registry.plugin_count == 4

    def test_plugin_config_values_are_applied(self) -> None:
        """The explicit mapping must still pass real settings through."""
        config = Config.default()
        config.plugins.wikipedia.language = "de"
        config.plugins.llm.model = "mistral"

        server = HandlerServer(config=config, transport=MockTransport())

        assert server.registry.get_by_name("Wikipedia")._language == "de"
        assert server.registry.get_by_name("LLM Assistant")._default_model == "mistral"
