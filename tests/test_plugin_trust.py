from core.plugin_loader import PluginRecord, PluginRegistry


def test_trust_model_flags_dangerous_permissions():
    registry = PluginRegistry({}, logger=lambda msg: None)
    rec = PluginRecord(
        name="danger_plugin",
        description="Executes commands",
        valid=True,
        permissions={"file_access", "shell_access"},
        signed=False,
    )

    decision = registry.evaluate_trust(rec)

    assert decision["risk_level"] == "high"
    assert decision["requires_confirmation"] is True
    assert decision["sandbox"] == "required"
    assert "shell_access" in decision["permissions"]


def test_trust_model_blocks_denylisted_plugins():
    registry = PluginRegistry({"blocked_plugin": PluginRecord(name="blocked_plugin", description="blocked", valid=True)},
                              logger=lambda msg: None,
                              denylist={"blocked_plugin"})
    rec = PluginRecord(name="blocked_plugin", description="blocked", valid=True, permissions=set())

    decision = registry.evaluate_trust(rec)

    assert decision["blocked"] is True
    assert "denylist" in decision["reason"].lower()


def test_trust_model_allows_safe_signed_plugins():
    registry = PluginRegistry({}, logger=lambda msg: None, allowlist={"safe_plugin"})
    rec = PluginRecord(
        name="safe_plugin",
        description="Safe plugin",
        valid=True,
        permissions={"network_access"},
        signed=True,
    )

    decision = registry.evaluate_trust(rec)

    assert decision["blocked"] is False
    assert decision["risk_level"] == "medium"
    assert decision["signed"] is True
