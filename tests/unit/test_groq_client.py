"""Unit tests for GroqClient key rotation."""

from unittest.mock import MagicMock, patch
import pytest


@patch("llm.groq_client.get_config")
def test_round_robin_rotation(mock_cfg):
    mock_cfg.return_value.get_groq_keys.return_value = ["key1", "key2", "key3"]
    mock_cfg.return_value.GROQ_MODEL = "llama3-70b-8192"

    with patch("llm.groq_client.Groq") as mock_groq_cls:
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Test response"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 20
        mock_response.usage.total_tokens = 30
        mock_groq_cls.return_value.chat.completions.create.return_value = mock_response

        from llm.groq_client import GroqClient
        client = GroqClient()

        # First 3 calls should rotate through all 3 keys
        used_indices = []
        for _ in range(3):
            _, meta = client.complete("hello")
            used_indices.append(meta["key_index"])

        assert sorted(used_indices) == [0, 1, 2]


@patch("llm.groq_client.get_config")
def test_rate_limit_retry(mock_cfg):
    mock_cfg.return_value.get_groq_keys.return_value = ["key1", "key2"]
    mock_cfg.return_value.GROQ_MODEL = "llama3-70b-8192"

    from groq import RateLimitError

    with patch("llm.groq_client.Groq") as mock_groq_cls:
        mock_success = MagicMock()
        mock_success.choices[0].message.content = "OK"
        mock_success.usage.prompt_tokens = 5
        mock_success.usage.completion_tokens = 5
        mock_success.usage.total_tokens = 10

        call_count = 0
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RateLimitError.__new__(RateLimitError)
            return mock_success

        mock_groq_cls.return_value.chat.completions.create.side_effect = side_effect

        from llm.groq_client import GroqClient
        client = GroqClient()
        text, meta = client.complete("hello")
        assert text == "OK"
        assert call_count == 2  # first key failed, second succeeded
