from memory import config_manager as cfg


def test_advanced_profile_is_default_and_full_featured():
    cfg.save_settings_profile("safe")
    assert cfg.get_settings_profile() == "advanced"
    assert cfg.is_safe_mode_enabled() is False
    assert cfg.get_advanced_settings_visible() is True

    sections = cfg.get_settings_sections()
    categories = {section["category"] for section in sections}
    assert "general" in categories
    assert "voice" in categories
    assert "advanced" in categories

    section_ids = {section["id"] for section in sections}
    assert "safe_mode" not in section_ids

    cfg.save_settings_profile("advanced")
