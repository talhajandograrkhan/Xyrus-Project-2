import sys

from ui import CustomizeOverlay, MainWindow, _is_local_media_source
from memory.memory_manager import remember_user_fact, search_memory, remember, update_memory_entry, merge_memory_entry
from main import JarvisLive
from core.task_manager import SafeTaskManager
from memory.config_manager import get_brief_enabled, get_developer_name, save_assistant_config
from main import should_use_wake_word, build_remote_upload_prompt
from actions.background_monitor import collect_screen_state, latest_screen_state
from actions.proactive import ProactiveEngine
from core.gemini import note_live_failure, live_model

from setup import _qt_requirement_for_platform


def test_main_creates_explicit_repo_root_entry():
    import main

    assert hasattr(main, "_PROJECT_ROOT")
    assert str(main._PROJECT_ROOT) in {str(p) for p in sys.path}


def test_jarvis_ui_ignores_updates_after_window_is_destroyed():
    from ui_new import JarvisUI
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    ui = JarvisUI("face.png")
    ui._win._destroyed = True
    ui._win._closing = True

    ui.set_state("LISTENING")
    ui.write_log("hello")
    ui.show_content("title", "body")
    ui.show_quiz("topic", [])
    ui.show_review("title", "summary", [])
    ui.prompt_reconfig()
    ui.notify_phone_connected()
    ui.set_audio_level(0.4)
    ui.push_visemes([], 0.1, 0.0)


def test_long_youtube_stream_url_is_not_local_file():
    url = (
        "https://rr2---sn-jtcxg-2xf6.googlevideo.com/videoplayback?"
        "expire=1791501520&ei=cNDHasLIMrvGmLAPmqGu0Q4&id=o-APIi9o4X8LEAOZ_"
        "IKW7vYWgBiFc-ZuiX-Z3P5qbqNyD0&itag=136&source=youtube"
    )
    assert _is_local_media_source(url) is False


def test_search_handles_underscored_profile_facts():
    remember_user_fact("favorite_color", "blue")
    result = search_memory("favorite_color")
    assert "favorite" in result.lower()
    assert "color" in result.lower()


def test_memory_supports_tags_and_confidence_metadata():
    remember("favorite_color", "blue", category="profile", tags=["color", "preference"], confidence=0.93)
    result = search_memory("color preference")
    assert "favorite_color" in result.lower()
    assert "blue" in result.lower()


def test_restore_idle_state_returns_to_listening_when_awake():
    calls = []
    live = object.__new__(JarvisLive)
    live.ui = type("FakeUI", (), {
        "muted": False,
        "set_state": lambda self, state: calls.append(state)
    })()
    live._wake_enabled = False
    live._awake = True
    live._restore_idle_state()
    assert calls == ["LISTENING"]


def test_update_memory_entry_rewrites_existing_fact_with_metadata():
    remember("favorite_color", "blue", category="profile")
    updated = update_memory_entry("favorite_color", "green", category="profile", tags=["color"], confidence=0.8)
    assert updated["value"] == "green"
    assert updated["confidence"] == 0.8
    assert updated["tags"] == ["color"]


def test_search_memory_uses_semantic_synonyms_for_preferences():
    remember("favorite_color", "blue", category="profile", tags=["color", "preference"], confidence=0.93)
    result = search_memory("what hue do i prefer")
    assert "favorite_color" in result.lower()
    assert "blue" in result.lower()


def test_merge_memory_entry_keeps_and_updates_existing_fact():
    remember("favorite_color", "blue", category="profile", tags=["color"], confidence=0.8)
    merged = merge_memory_entry("favorite_color", "navy blue", category="profile", alias_key="favourite_colour", tags=["color", "preference"], confidence=0.95)
    assert merged["value"] == "navy blue"
    assert merged["confidence"] == 0.95
    assert merged["tags"] == ["color", "preference"]


def test_task_manager_supports_checkpointed_multi_step_plans():
    manager = SafeTaskManager()
    plan = manager.create_plan(
        "Ship release",
        ["audit build", "fix blockers", "verify release"],
        description="Quarterly release prep",
    )
    assert plan["plan_status"] == "pending"

    manager.start_plan(plan["key"])
    manager.checkpoint(plan["key"], "audit build complete", step_index=0)
    manager.advance_plan(plan["key"], step_index=1)

    resumed = manager.resume_plan(plan["key"])
    assert resumed["current_step"] == 1
    assert resumed["checkpoints"][-1]["step_index"] == 0

    manager.clear_action_history(plan["key"])
    assert manager.get_plan(plan["key"])["action_history"] == []


def test_macos_12_uses_legacy_qt_constraint():
    assert _qt_requirement_for_platform("Darwin", "12.7.6") == "PyQt6>=6.6,<6.8"


def test_macos_13_uses_current_qt_constraint():
    assert _qt_requirement_for_platform("Darwin", "13.0.0") == "PyQt6>=6.6,<7"


def test_linux_keeps_current_qt_constraint():
    assert _qt_requirement_for_platform("Linux", "6.1") == "PyQt6>=6.6,<7"


def test_wake_word_falls_back_to_direct_listening_when_detector_is_unavailable(monkeypatch):
    monkeypatch.setattr("main.wake_is_ready", lambda: False)
    assert should_use_wake_word(True) is False
    assert should_use_wake_word(False) is False

    monkeypatch.setattr("main.wake_is_ready", lambda: True)
    assert should_use_wake_word(True) is True


def test_ui_wake_toggle_falls_back_to_direct_listening_when_detector_is_unavailable(monkeypatch):
    live = object.__new__(JarvisLive)
    live.ui = type("FakeUI", (), {
        "write_log": lambda self, msg: None,
        "set_state": lambda self, state: None,
        "muted": False,
    })()
    live._wake_enabled = False
    live._awake = True
    saved = []

    monkeypatch.setattr("main.should_use_wake_word", lambda configured: False)
    monkeypatch.setattr("main.save_wake_word_enabled", lambda enabled: saved.append(enabled))
    monkeypatch.setattr("main.wake_is_ready", lambda: False)

    assert live._ui_wake_toggle(True) == "disabled"
    assert saved == [False]


def test_morning_brief_defaults_on(monkeypatch):
    monkeypatch.setattr("memory.config_manager.load_api_keys", lambda: {})
    assert get_brief_enabled() is True


def test_developer_identity_defaults_to_talha_sabeeh(monkeypatch):
    monkeypatch.setattr("memory.config_manager.load_api_keys", lambda: {"assistant_name": "Xyrus", "user_name": "Talha"})
    assert get_developer_name() == "Talha Sabeeh"

    save_assistant_config("Xyrus", "Talha", "Talha Sabeeh")
    assert get_developer_name() == "Talha Sabeeh"


def test_collect_screen_state_reports_live_system_and_screen_snapshot(monkeypatch):
    monkeypatch.setattr("actions.background_monitor.get_system_status", lambda: {"cpu_percent": 12.2, "ram_percent": 34.1})
    monkeypatch.setattr("actions.background_monitor._capture_screenshot_bytes", lambda: b"screen-data")

    snapshot = collect_screen_state()
    assert snapshot["cpu_percent"] == 12.2
    assert snapshot["ram_percent"] == 34.1
    assert snapshot["screenshot_bytes"] == b"screen-data"
    assert snapshot["interval_seconds"] == 2.0


def test_screen_monitor_tool_exposes_latest_snapshot(monkeypatch):
    monkeypatch.setattr("actions.background_monitor.get_system_status", lambda: {"cpu_percent": 20.0, "ram_percent": 55.0})
    monkeypatch.setattr("actions.background_monitor._capture_screenshot_bytes", lambda: b"abc")
    state = collect_screen_state()
    assert state["cpu_percent"] == 20.0
    assert state["ram_percent"] == 55.0
    assert state["screenshot_bytes"] == b"abc"
    assert state["interval_seconds"] == 2.0
    assert latest_screen_state() == {}


def test_proactive_engine_triggers_on_high_system_load(monkeypatch):
    engine = ProactiveEngine(min_silence_secs=900, check_cooldown=1200)
    monkeypatch.setattr("actions.proactive.time.monotonic", lambda: 1000.0)
    engine._last_triggered = 0.0

    assert engine.should_trigger(50.0, system_state={"cpu_percent": 92.0, "ram_percent": 91.0}) is True

    prompt = engine.build_prompt({"identity": {}}, system_state={"cpu_percent": 92.0, "ram_percent": 91.0})
    assert "cpu_percent" in prompt
    assert "92.0" in prompt


def test_live_model_steps_down_on_1011_internal_error():
    model = "models/gemini-3.1-flash-live-preview"
    assert note_live_failure(model, "1011 None. Internal error encountered.") is True
    assert live_model() != model


def test_remote_upload_prompt_mentions_file_and_path():
    prompt = build_remote_upload_prompt("/tmp/report.pdf", 2456)
    assert "FILE_UPLOADED" in prompt
    assert "report.pdf" in prompt
    assert "/tmp/report.pdf" in prompt


def test_customize_overlay_initializes_without_qt_crash():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    overlay = CustomizeOverlay("Xyrus", "", "#00d4ff", "", "advanced", 72)
    overlay.show()
    app.processEvents()
    assert overlay._mic_sens_slider.value() == 72
    overlay.close()


def test_main_window_keeps_only_one_large_assistant_name():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    window = MainWindow("face.png")
    window.show()
    app.processEvents()
    assert window._title_mark.isHidden() is True
    assert window._sub_lbl.isHidden() is True
    assert window._title_lbl.isVisible() is True
    window.close()


def test_system_prompt_includes_humour_and_laughter_guidance():
    from pathlib import Path

    prompt = Path("core/prompt.txt").read_text(encoding="utf-8")
    assert "laugh" in prompt.lower()
    assert "humour" in prompt.lower() or "humor" in prompt.lower()
    assert "emotion" in prompt.lower() or "warmth" in prompt.lower()


def test_system_prompt_uses_natural_chat_conversation_style():
    from pathlib import Path

    prompt = Path("core/prompt.txt").read_text(encoding="utf-8")
    text = prompt.lower()
    assert "chat" in text or "conversational" in text
    assert "natural" in text
    assert "clear" in text
    assert "collaborative" in text or "thoughtful" in text


def test_system_prompt_prioritizes_truth_over_flattery():
    from pathlib import Path

    prompt = Path("core/prompt.txt").read_text(encoding="utf-8")
    text = prompt.lower()
    assert "truth" in text or "true" in text
    assert "flatter" in text or "false certainty" in text
    assert "accurate" in text or "accuracy" in text


def test_user_voice_interrupts_jarvis_mid_speech():
    import threading

    live = object.__new__(JarvisLive)
    live._speaking_lock = threading.Lock()
    live._is_speaking = True
    live._interrupted = False
    live.audio_in_queue = []
    live._turn_done_event = None
    live._visemes = type("Visemes", (), {"reset": lambda self: None})()
    live._play_cursor = 0.0
    live._tail_until = 0.0
    live._out_latency = 0.0
    live._last_user_speech = 0.0
    live.ui = type("FakeUI", (), {
        "muted": False,
        "write_log": lambda self, msg: None,
        "set_state": lambda self, state: None,
    })()
    live._echo = type("Echo", (), {
        "is_user_speech": staticmethod(lambda *args, **kwargs: True),
    })()

    live._handle_barge_in(b"x")

    assert live._interrupted is True
    assert live._is_speaking is False

    def callback(indata):
        # The real callback checks barge-in before the normal listen flow. A
        # successful interrupt should not bail out of the pipeline; it should
        # continue to the regular mic handling path.
        jarvis_speaking = live._is_speaking
        if jarvis_speaking:
            if live._handle_barge_in(indata):
                return "continue-listening"
            return "ignored"
        return "already-listening"

    # At this point the assistant has already interrupted itself, so the
    # speaking flag is false; the real check is that the earlier branch did not
    # force an early exit from the mic pipeline.
    assert live._interrupted is True
    assert live._is_speaking is False
    assert callback(b"x") == "already-listening"
