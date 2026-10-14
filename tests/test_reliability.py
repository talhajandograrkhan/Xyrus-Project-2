import core.gemini as gemini
from app.services.system_actions import SystemActionService
from memory.config_manager import save_settings_profile, get_settings_profile, is_safe_mode_enabled


def test_only_advanced_profile_is_supported():
    save_settings_profile("safe")
    assert get_settings_profile() == "advanced"
    assert is_safe_mode_enabled() is False

    save_settings_profile("advanced")
    assert get_settings_profile() == "advanced"
    assert is_safe_mode_enabled() is False


def test_startup_summary_lists_runtime_components():
    service = SystemActionService()
    report = service.startup_report()

    text = report.lower()
    for needle in ("microphone", "speaker", "camera", "memory", "model", "plugins"):
        assert needle in text


def test_microphone_gain_boosts_quiet_input_without_clipping():
    import numpy as np

    from main import _apply_input_gain

    quiet = np.array([100, 80, -60, -90], dtype=np.int16)
    boosted = _apply_input_gain(quiet)

    assert np.max(np.abs(boosted)) <= np.iinfo(np.int16).max
    assert np.abs(boosted).mean() > np.abs(quiet).mean()


def test_voice_profile_recognizes_repeat_speakers_and_unknown_people(tmp_path):
    import numpy as np

    from memory.voice_recognition import VoiceProfileStore

    store = VoiceProfileStore(path=tmp_path / "voice_profiles.json")

    base = np.array([
        0, 140, -90, 80, 10, -20, 30, -40, 50, 60,
        0, 110, -70, 75, 15, -25, 40, -35, 55, 65,
    ] * 64, dtype=np.int16)
    similar = np.array([
        0, 150, -95, 85, 12, -18, 32, -44, 52, 58,
        0, 120, -72, 80, 18, -24, 38, -38, 58, 62,
    ] * 64, dtype=np.int16)
    noise = np.array([
        1, -2, 4, -5, 7, -8, 3, -3, 6, -7,
        2, -1, 5, -6, 8, -9, 4, -2, 7, -8,
    ] * 64, dtype=np.int16)

    store.register_voice("Talha", base)
    name, score = store.recognize_voice(similar)
    assert name == "Talha"
    assert score < 0.5
    assert store.recognize_voice(noise)[0] is None


def test_voice_store_stays_unblocked_until_a_voice_has_been_saved(tmp_path):
    import numpy as np

    from memory.voice_recognition import VoiceProfileStore

    store = VoiceProfileStore(path=tmp_path / "voice_profiles.json")
    assert store.has_known_voices() is False

    base = np.array([
        0, 140, -90, 80, 10, -20, 30, -40, 50, 60,
        0, 110, -70, 75, 15, -25, 40, -35, 55, 65,
    ] * 64, dtype=np.int16)
    store.register_voice("Talha", base)
    assert store.has_known_voices() is True


def test_unknown_voice_prompts_for_intro_and_saves_profile(tmp_path):
    import numpy as np

    from main import JarvisLive
    from memory.voice_recognition import VoiceProfileStore

    class DummyUI:
        def __init__(self):
            self.logged = []
            self.said = []
            self.state = "LISTENING"
        def write_log(self, msg):
            self.logged.append(msg)
        def request_say(self, msg):
            self.said.append(msg)
        def set_state(self, state):
            self.state = state

    ui = DummyUI()
    live = JarvisLive.__new__(JarvisLive)
    live.ui = ui
    live._voice_profile_store = VoiceProfileStore(path=tmp_path / "voice_profiles.json")
    live._voice_intro_pending = False
    live._voice_intro_audio = None
    live._voice_intro_samples = []
    live._pending_unknown_voice = None

    sample = np.array([0, 140, -90, 80, 10, -20, 30, -40, 50, 60] * 64, dtype=np.int16)
    assert live._handle_voice_gate(sample) is True
    assert live._voice_intro_pending is False
    assert not ui.said

    live._voice_profile_store.register_voice("Talha", sample)
    other = np.array([1, -2, 4, -5, 7, -8, 3, -3, 6, -7] * 64, dtype=np.int16)
    assert live._handle_voice_gate(other) is False
    assert live._voice_intro_pending is True
    assert ui.state == "INTRO_REQUIRED"
    assert ui.said

    live._voice_intro_from_text("My name is Talha")
    assert live._voice_profile_store.known_names() == ["Talha"]
    assert live._voice_intro_pending is False


def test_face_store_recognizes_known_face_and_rejects_unknown_face(tmp_path):
    import numpy as np

    from memory.voice_recognition import FaceProfileStore

    store = FaceProfileStore(path=tmp_path / "face_profiles.json")
    base = np.zeros((120, 120, 3), dtype=np.uint8)
    base[20:100, 20:100] = 200
    base[35:85, 35:85] = 150
    base[45:75, 45:75] = 80

    store.register_face("Talha", base)
    assert store.recognize_face(base)[0] == "Talha"

    other = np.zeros((120, 120, 3), dtype=np.uint8)
    other[:, :] = 30
    other[10:110, 10:110] = 200
    assert store.recognize_face(other)[0] is None


def test_voice_store_tracks_multiple_samples_per_person(tmp_path):
    import numpy as np

    from memory.voice_recognition import VoiceProfileStore

    store = VoiceProfileStore(path=tmp_path / "voice_profiles.json")
    base = np.array([
        0, 140, -90, 80, 10, -20, 30, -40, 50, 60,
        0, 110, -70, 75, 15, -25, 40, -35, 55, 65,
    ] * 64, dtype=np.int16)
    similar = np.array([
        0, 150, -95, 85, 12, -18, 32, -44, 52, 58,
        0, 120, -72, 80, 18, -24, 38, -38, 58, 62,
    ] * 64, dtype=np.int16)

    store.register_voice("Talha", [base, similar])
    profile = store._profiles["known"]["Talha"]
    assert len(profile["samples"]) == 2
    assert store.recognize_voice(base)[0] == "Talha"
    assert store.recognize_voice(similar)[0] == "Talha"
    assert store.recognize_voice(np.array([1, -2, 4, -5, 7, -8, 3, -3, 6, -7] * 64, dtype=np.int16))[0] is None


def test_health_status_exposes_components_and_failure_reason():
    service = SystemActionService()
    service.record_failure("browser_control", "timeout")
    status = service.health_status()

    assert "mic" in status
    assert "speaker" in status
    assert "camera" in status
    assert "memory" in status
    assert "model_ladder" in status
    assert "plugin_load_state" in status
    assert status["last_failure"] == "timeout"
    assert status["last_action"] == "browser_control"


def test_model_text_falls_back_safely_when_generation_fails(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("quota exhausted")

    monkeypatch.setattr(gemini, "call", _boom)
    out = gemini.text("test", default="I could not complete that request right now. Please try again in a moment.")
    assert "could not complete" in out.lower()
