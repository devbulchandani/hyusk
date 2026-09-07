"""Configuration management for Hyusk."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMConfig(BaseSettings):
    """LLM configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Map environment variables without prefix
        # e.g., DEFAULT_LLM_PROVIDER -> default_provider
    )

    default_provider: str = Field(
        default="anthropic",
        validation_alias="DEFAULT_LLM_PROVIDER",
    )
    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias="ANTHROPIC_API_KEY",
    )
    openai_api_key: str | None = Field(
        default=None,
        validation_alias="OPENAI_API_KEY",
    )

    # Base URLs for custom endpoints (e.g., OpenRouter, local servers)
    openai_base_url: str | None = Field(
        default=None,
        validation_alias="OPENAI_BASE_URL",
    )
    anthropic_base_url: str | None = Field(
        default=None,
        validation_alias="ANTHROPIC_BASE_URL",
    )

    # Model routing
    default_model: str = Field(
        default="claude-sonnet-4",
        validation_alias="DEFAULT_MODEL",
    )
    fast_model: str = Field(
        default="claude-haiku-3.5",
        validation_alias="FAST_MODEL",
    )
    coding_model: str = Field(
        default="claude-sonnet-4",
        validation_alias="CODING_MODEL",
    )
    vision_model: str = Field(
        default="claude-sonnet-4",
        validation_alias="VISION_MODEL",
    )
    local_model: str | None = Field(
        default=None,
        validation_alias="LOCAL_MODEL",
    )

    # Defaults
    max_tokens: int = Field(
        default=4096,
        validation_alias="MAX_TOKENS",
    )
    temperature: float = Field(
        default=0.7,
        validation_alias="TEMPERATURE",
    )
    timeout: int = Field(
        default=120,
        validation_alias="LLM_TIMEOUT",
    )


class VoiceConfig(BaseSettings):
    """Voice configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = Field(
        default=False,
        validation_alias="VOICE_ENABLED",
    )
    wake_word: str = Field(
        default="hey hyusk",
        validation_alias="WAKE_WORD",
    )

    # STT
    stt_provider: str = Field(
        default="whisper",
        validation_alias="STT_PROVIDER",
    )
    stt_model: str = Field(
        default="base",
        validation_alias="STT_MODEL",
    )
    stt_language: str = Field(
        default="en",
        validation_alias="STT_LANGUAGE",
    )

    # TTS
    tts_provider: str = Field(
        default="kokoro",
        validation_alias="TTS_PROVIDER",
    )
    tts_voice: str = Field(
        default="default",
        validation_alias="TTS_VOICE",
    )
    tts_speed: float = Field(
        default=1.0,
        validation_alias="TTS_SPEED",
    )


class PermissionConfig(BaseSettings):
    """Permission configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    auto_approve_safe: bool = Field(
        default=True,
        validation_alias="AUTO_APPROVE_SAFE",
    )
    approval_timeout: int = Field(
        default=300,  # seconds
        validation_alias="APPROVAL_TIMEOUT",
    )
    require_confirmation: list[str] = Field(
        default_factory=lambda: ["write_file", "terminal_execute", "delete_file"],
        validation_alias="REQUIRE_CONFIRMATION",
    )


class ComputerConfig(BaseSettings):
    """Computer control configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    platform: str = Field(
        default="macos",
        validation_alias="COMPUTER_PLATFORM",
    )
    screenshot_format: str = Field(
        default="png",
        validation_alias="SCREENSHOT_FORMAT",
    )
    screenshot_quality: int = Field(
        default=85,
        validation_alias="SCREENSHOT_QUALITY",
    )


class AgentConfig(BaseSettings):
    """Agent configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    max_concurrent: int = Field(
        default=5,
        validation_alias="AGENT_MAX_CONCURRENT",
    )
    workspace_dir: str = Field(
        default="~/.hyusk/workspaces",
        validation_alias="AGENT_WORKSPACE_DIR",
    )
    default_timeout: int = Field(
        default=3600,  # seconds
        validation_alias="AGENT_DEFAULT_TIMEOUT",
    )
    cleanup_on_completion: bool = Field(
        default=False,
        validation_alias="AGENT_CLEANUP_ON_COMPLETION",
    )


class MemoryConfig(BaseSettings):
    """Memory configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = Field(
        default=True,
        validation_alias="MEMORY_ENABLED",
    )
    vector_search: bool = Field(
        default=False,
        validation_alias="MEMORY_VECTOR_SEARCH",
    )
    max_conversation_history: int = Field(
        default=100,
        validation_alias="MEMORY_MAX_CONVERSATION_HISTORY",
    )
    memory_retention_days: int = Field(
        default=90,
        validation_alias="MEMORY_RETENTION_DAYS",
    )


class RemoteConfig(BaseSettings):
    """Remote API configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    enabled: bool = Field(
        default=False,
        validation_alias="REMOTE_ENABLED",
    )
    host: str = Field(
        default="localhost",
        validation_alias="REMOTE_HOST",
    )
    port: int = Field(
        default=8765,
        validation_alias="REMOTE_PORT",
    )
    secret_key: str = Field(
        default="change-me-in-production",
        validation_alias="REMOTE_SECRET_KEY",
    )
    tls_enabled: bool = Field(
        default=False,
        validation_alias="REMOTE_TLS_ENABLED",
    )
    tls_cert: str | None = Field(
        default=None,
        validation_alias="REMOTE_TLS_CERT",
    )
    tls_key: str | None = Field(
        default=None,
        validation_alias="REMOTE_TLS_KEY",
    )


class DatabaseConfig(BaseSettings):
    """Database configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    url: str = Field(
        default="sqlite+aiosqlite:///~/.hyusk/hyusk.db",
        validation_alias="DATABASE_URL",
    )
    echo: bool = Field(
        default=False,
        validation_alias="DATABASE_ECHO",
    )
    pool_size: int = Field(
        default=5,
        validation_alias="DATABASE_POOL_SIZE",
    )


class LoggingConfig(BaseSettings):
    """Logging configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    level: str = Field(
        default="INFO",
        validation_alias="LOG_LEVEL",
    )
    file: str = Field(
        default="~/.hyusk/hyusk.log",
        validation_alias="LOG_FILE",
    )
    format: str = Field(
        default="json",
        validation_alias="LOG_FORMAT",
    )
    max_size_mb: int = Field(
        default=100,
        validation_alias="LOG_MAX_SIZE_MB",
    )
    backup_count: int = Field(
        default=5,
        validation_alias="LOG_BACKUP_COUNT",
    )


class HyuskConfig(BaseSettings):
    """Main Hyusk configuration."""

    model_config = SettingsConfigDict(
        env_prefix="HYUSK_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Allow extra fields from env/config files
    )

    # Config file path
    config_file: str = "~/.config/hyusk/config.yaml"

    # Sub-configs
    llm: LLMConfig = Field(default_factory=LLMConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    permissions: PermissionConfig = Field(default_factory=PermissionConfig)
    computer: ComputerConfig = Field(default_factory=ComputerConfig)
    agents: AgentConfig = Field(default_factory=AgentConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    remote: RemoteConfig = Field(default_factory=RemoteConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    # General settings
    hyusk_dir: str = "~/.hyusk"
    debug: bool = False

    @classmethod
    def load(cls, config_path: str | None = None) -> "HyuskConfig":
        """Load configuration from file and environment."""
        # Start with defaults
        config_dict: dict[str, Any] = {}

        # Try to load from YAML file
        if config_path:
            config_file = Path(config_path).expanduser()
        else:
            config_file = Path("~/.config/hyusk/config.yaml").expanduser()

        if config_file.exists():
            with open(config_file) as f:
                config_dict = yaml.safe_load(f) or {}

        # Create config object (will also load from env)
        return cls(**config_dict)

    def save(self, config_path: str | None = None) -> None:
        """Save configuration to file."""
        if config_path:
            config_file = Path(config_path).expanduser()
        else:
            config_file = Path(self.config_file).expanduser()

        config_file.parent.mkdir(parents=True, exist_ok=True)

        # Convert to dict and save
        config_dict = self.model_dump(exclude={"config_file"})

        with open(config_file, "w") as f:
            yaml.safe_dump(config_dict, f, default_flow_style=False, sort_keys=False)

    def ensure_directories(self) -> None:
        """Ensure required directories exist."""
        dirs = [
            self.hyusk_dir,
            self.agents.workspace_dir,
            Path(self.logging.file).parent,
            Path(
                self.database.url.replace("sqlite+aiosqlite:///", "").replace("~", str(Path.home()))
            ).parent,
        ]

        for dir_path in dirs:
            path = Path(dir_path).expanduser()
            path.mkdir(parents=True, exist_ok=True)


# Global config instance
_config: HyuskConfig | None = None


def get_config() -> HyuskConfig:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = HyuskConfig.load()
    return _config


def set_config(config: HyuskConfig) -> None:
    """Set the global configuration instance."""
    global _config
    _config = config
