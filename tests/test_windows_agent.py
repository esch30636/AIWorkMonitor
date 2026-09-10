from pathlib import Path

import pytest

from aiworkmonitor.windows_agent import load_config_file


def test_load_config_file_uses_aiwm_keys_and_preserves_environment(tmp_path, monkeypatch) -> None:
    config = tmp_path / "aiworkmonitor.env"
    config.write_text(
        "AIWM_TOKEN=file-token\n"
        "AIWM_DEVICE_NAME=Office PC\n"
        "AIWM_CLAUDE_WORKDIR=project\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIWM_TOKEN", "environment-token")

    assert load_config_file(config)
    assert __import__("os").environ["AIWM_TOKEN"] == "environment-token"
    assert __import__("os").environ["AIWM_DEVICE_NAME"] == "Office PC"
    assert Path(__import__("os").environ["AIWM_CLAUDE_WORKDIR"]) == tmp_path / "project"


def test_load_config_file_rejects_unknown_keys(tmp_path) -> None:
    config = tmp_path / "aiworkmonitor.env"
    config.write_text("PATH=unsafe\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported key"):
        load_config_file(config)
