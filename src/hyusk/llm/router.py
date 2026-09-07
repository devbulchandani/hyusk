"""LLM router for selecting and managing providers."""

from hyusk.config import get_config
from hyusk.llm.base import LLMProvider
from hyusk.llm.providers.anthropic import AnthropicProvider
from hyusk.llm.providers.openai import OpenAIProvider
from hyusk.logging import get_logger

logger = get_logger(__name__)


class ModelType:
    """Model type identifiers for routing."""

    DEFAULT = "default"
    FAST = "fast"
    CODING = "coding"
    VISION = "vision"
    LOCAL = "local"


class LLMRouter:
    """Routes LLM requests to appropriate providers and models."""

    def __init__(self) -> None:
        self.config = get_config()
        self._providers: dict[str, LLMProvider] = {}

    def get_provider(self, model_type: str = ModelType.DEFAULT) -> LLMProvider:
        """Get or create a provider for the specified model type.

        Args:
            model_type: Type of model to use (default, fast, coding, vision, local)

        Returns:
            LLMProvider instance

        Raises:
            ValueError: If provider is not configured
        """
        # Check cache
        if model_type in self._providers:
            return self._providers[model_type]

        # Determine model and provider
        model = self._get_model_for_type(model_type)
        provider_name = self.config.llm.default_provider

        logger.info(
            f"Creating provider for {model_type}",
            provider=provider_name,
            model=model,
        )

        # Create provider
        provider = self._create_provider(provider_name, model)

        # Cache it
        self._providers[model_type] = provider

        return provider

    def clear_cache(self) -> None:
        """Clear provider cache."""
        self._providers.clear()
        logger.info("Cleared LLM provider cache")

    def _get_model_for_type(self, model_type: str) -> str:
        """Get model name for a given type.

        Args:
            model_type: Model type

        Returns:
            Model name
        """
        mapping = {
            ModelType.DEFAULT: self.config.llm.default_model,
            ModelType.FAST: self.config.llm.fast_model,
            ModelType.CODING: self.config.llm.coding_model,
            ModelType.VISION: self.config.llm.vision_model,
            ModelType.LOCAL: self.config.llm.local_model,
        }

        model = mapping.get(model_type)

        if not model:
            logger.warning(
                f"Model type {model_type} not configured, using default",
                default_model=self.config.llm.default_model,
            )
            model = self.config.llm.default_model

        return model

    def _create_provider(self, provider_name: str, model: str) -> LLMProvider:
        """Create a provider instance.

        Args:
            provider_name: Provider name (anthropic, openai)
            model: Model name

        Returns:
            LLMProvider instance

        Raises:
            ValueError: If provider is unknown or not configured
        """
        if provider_name == "anthropic":
            if not self.config.llm.anthropic_api_key:
                raise ValueError(
                    "Anthropic API key not configured. Set ANTHROPIC_API_KEY in .env or config"
                )

            return AnthropicProvider(
                model=model,
                api_key=self.config.llm.anthropic_api_key,
                max_tokens=self.config.llm.max_tokens,
                temperature=self.config.llm.temperature,
                timeout=self.config.llm.timeout,
                base_url=self.config.llm.anthropic_base_url,
            )

        elif provider_name == "openai":
            if not self.config.llm.openai_api_key:
                raise ValueError(
                    "OpenAI API key not configured. Set OPENAI_API_KEY in .env or config"
                )

            return OpenAIProvider(
                model=model,
                api_key=self.config.llm.openai_api_key,
                max_tokens=self.config.llm.max_tokens,
                temperature=self.config.llm.temperature,
                timeout=self.config.llm.timeout,
                base_url=self.config.llm.openai_base_url,
            )

        else:
            raise ValueError(f"Unknown provider: {provider_name}")

    def select_model_for_task(
        self,
        needs_vision: bool = False,
        needs_speed: bool = False,
        needs_coding: bool = False,
    ) -> str:
        """Select appropriate model type based on task requirements.

        Args:
            needs_vision: Task requires image understanding
            needs_speed: Task prioritizes speed
            needs_coding: Task involves code generation/analysis

        Returns:
            Model type identifier
        """
        if needs_vision:
            return ModelType.VISION
        elif needs_coding:
            return ModelType.CODING
        elif needs_speed:
            return ModelType.FAST
        else:
            return ModelType.DEFAULT


# Global router instance
_router: LLMRouter | None = None


def get_router() -> LLMRouter:
    """Get the global LLM router instance."""
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router


def set_router(router: LLMRouter) -> None:
    """Set the global LLM router instance."""
    global _router
    _router = router
