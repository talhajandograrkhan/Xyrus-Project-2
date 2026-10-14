"""Model connection configuration helpers for the live Gemini runtime."""

from __future__ import annotations


class ModelConnection:
    """Keeps the live model and connection settings in one dedicated layer."""

    def __init__(self, model: str = "models/gemini-3.1-flash-live-preview", api_version: str = "v1alpha"):
        self.model = model
        self.api_version = api_version

    def build_config(self, *, tools=None, system_instruction=None, speech_config=None, **kwargs):
        config = {
            "response_modalities": ["AUDIO"],
            "output_audio_transcription": {},
            "input_audio_transcription": {},
            "tools": tools or [],
            "system_instruction": system_instruction or "",
        }
        if speech_config is not None:
            config["speech_config"] = speech_config
        config.update(kwargs)
        return config

    def connect(self, client, model: str | None = None, config=None):
        model_name = model or self.model
        if config is None:
            config = self.build_config()
        return client.aio.live.connect(model=model_name, config=config)


__all__ = ["ModelConnection"]
