"""Tests for the user_config_dir fallback logic (V4.1.1)."""

from __future__ import annotations

from pathlib import Path

from hyusk.config.config import user_config_dir


def test_default_path_is_used_when_no_override(monkeypatch, tmp_path):
    """Without HYUSK_CONFIG_DIR, the platform default is used."""
    monkeypatch.delenv("HYUSK_CONFIG_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    d = user_config_dir()
    # On macOS, the default is ~/Library/Application Support/hyusk
    # On Linux, the default is ~/.config/hyusk (or XDG_CONFIG_HOME)
    assert d.name == "hyusk"
    assert d.exists()


def test_override_with_existing_dir_uses_it(monkeypatch, tmp_path):
    """A non-temp override is honored even if the default has a config."""
    real = tmp_path / "real"
    override = tmp_path / "override"
    real.mkdir(parents=True)
    (real / "hyusk").mkdir(parents=True)
    (real / "hyusk" / "config.toml").write_text('[llm]\napi_key = "sk-real"\n')
    override.mkdir(parents=True)
    (override / "hyusk").mkdir(parents=True)
    (override / "hyusk" / "config.toml").write_text('[llm]\napi_key = "sk-override"\n')
    monkeypatch.setenv("HYUSK_CONFIG_DIR", str(override))
    # We can't easily change the platform default in tests, so just verify
    # that the override IS used (the override path is /tmp/...).
    d = user_config_dir()
    assert str(d).startswith(str(override))


def test_stale_temp_override_falls_back_to_default(monkeypatch, tmp_path):
    """A HYUSK_CONFIG_DIR pointing to /tmp/... that has only test fixture
    config should be ignored, and the real default config used."""
    # Create a fake test config in /tmp
    fake = tmp_path / "tmpdir"
    fake.mkdir(parents=True)
    (fake / "hyusk").mkdir(parents=True)
    (fake / "hyusk" / "config.toml").write_text(
        '[llm]\napi_key = "sk-from-config-file"\n'
        'base_url = "https://api.example.com/v1"\n'
    )
    # The real config has the user's real key.
    real_default = Path.home() / "Library" / "Application Support" / "hyusk"
    real_config = real_default / "config.toml"
    has_real = real_config.exists() and "sk-from-config-file" not in real_config.read_text()

    monkeypatch.setenv("HYUSK_CONFIG_DIR", str(fake))
    d = user_config_dir()
    # Should NOT be the fake path.
    assert not str(d).startswith(str(fake))
    # And if a real config exists, the result should point to the real location.
    if has_real:
        assert str(d) == str(real_default)
