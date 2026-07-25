"""
src/utils/retry.py
──────────────────
Centralized retry / backoff decorators using tenacity.
Used for OpenAI API calls and flaky network requests.
"""

from __future__ import annotations

import logging

from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

logger = logging.getLogger(__name__)


def llm_retry(max_attempts: int = 5, min_wait: int = 2, max_wait: int = 60):
    """
    Decorator for OpenAI API calls.
    Retries on RateLimitError (HTTP 429) with exponential backoff.
    """
    # openai raises openai.RateLimitError on 429
    try:
        from openai import RateLimitError, APITimeoutError, APIConnectionError
        retryable = (RateLimitError, APITimeoutError, APIConnectionError)
    except ImportError:
        # Fallback if openai isn't installed yet
        retryable = (Exception,)

    return retry(
        retry=retry_if_exception_type(retryable),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )


def network_retry(max_attempts: int = 3, min_wait: int = 1, max_wait: int = 10):
    """
    Decorator for general network operations (aiohttp, playwright).
    """
    import aiohttp

    return retry(
        retry=retry_if_exception_type((aiohttp.ClientError, TimeoutError, ConnectionError)),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
