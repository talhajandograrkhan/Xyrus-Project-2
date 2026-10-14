from app.services.ai_orchestration import AIOrchestrationService
from app.services.memory_service import MemoryService
from app.services.plugin_lifecycle import PluginLifecycleService
from app.services.system_actions import SystemActionService


def test_service_layer_exports_expected_classes():
    assert callable(AIOrchestrationService)
    assert callable(SystemActionService)
    assert callable(MemoryService)
    assert callable(PluginLifecycleService)


def test_ai_service_sets_default_model():
    service = AIOrchestrationService()
    assert service.model == "models/gemini-3.1-flash-live-preview"


def test_memory_service_tracks_entries():
    service = MemoryService()
    service.store("identity", "name", "Alex")
    assert service.get("identity", "name") == "Alex"


def test_plugin_service_tracks_registry_and_lifecycle():
    service = PluginLifecycleService()
    service.register("demo_plugin")
    assert "demo_plugin" in service.list_plugins()
    assert service.is_loaded("demo_plugin") is True


def test_system_service_reports_health_status():
    service = SystemActionService()
    status = service.system_status()
    assert isinstance(status, dict)
    assert "cpu" in status or "memory" in status
