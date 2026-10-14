from main import build_remote_upload_prompt, should_use_wake_word


def test_main_module_exports_expected_helpers():
    assert callable(should_use_wake_word)
    assert callable(build_remote_upload_prompt)


def test_remote_upload_prompt_keeps_file_path_and_name():
    prompt = build_remote_upload_prompt("/tmp/report.pdf", 2456)
    assert "FILE_UPLOADED" in prompt
    assert "/tmp/report.pdf" in prompt
    assert "report.pdf" in prompt
