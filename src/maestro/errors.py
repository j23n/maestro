"""Provider-agnostic exceptions for external API failures.

Used by both the Anthropic LLM wrapper (llm.py) and the Azure TTS wrapper
(tts.py) so callers never import provider-specific error types.
"""


class APIUnavailableError(Exception):
    """Base: an external API cannot be reached or refused the request."""

    def __init__(self, message: str = "", *, provider: str | None = None):
        super().__init__(message)
        self.provider = provider


class APIRateLimitError(APIUnavailableError):
    """The external API returned a rate-limit response (HTTP 429)."""


class APITimeoutError(APIUnavailableError):
    """The request to the external API timed out."""


class APIStatusError(APIUnavailableError):
    """The external API returned a non-retryable HTTP error."""

    def __init__(
        self,
        message: str = "",
        *,
        status_code: int = 0,
        provider: str | None = None,
    ):
        super().__init__(message, provider=provider)
        self.status_code = status_code
