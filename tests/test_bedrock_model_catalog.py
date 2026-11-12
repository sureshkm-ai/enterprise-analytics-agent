"""Bedrock catalog and capability distinctions require no SDK or credentials."""

from typing import Any

import boto3
import pytest
from pydantic import ValidationError

from enterprise_analytics_agent.adapters.bedrock_model_catalog import (
    BEDROCK_MODELS,
    get_model,
    model_catalog,
)


def test_catalog_is_offline_immutable_metadata_not_access_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("reading model metadata must not create an AWS session")

    monkeypatch.setattr(boto3, "Session", forbidden)
    assert model_catalog() is BEDROCK_MODELS
    assert len({item.key for item in model_catalog()}) == len(model_catalog()) == 11
    assert {item.provider for item in model_catalog()} >= {
        "Anthropic",
        "OpenAI",
        "Google",
        "Meta",
        "DeepSeek",
        "Qwen",
        "Mistral AI",
    }
    for item in model_catalog():
        assert item.regions == ("us-west-2",)
        assert "does not establish account access" in item.eligibility_note
        assert item.reference_url.startswith("https://docs.aws.amazon.com/")
    with pytest.raises(ValidationError):
        get_model("nova-lite").label = "Injected label"  # type: ignore[misc]


@pytest.mark.parametrize(
    "key,expected",
    [
        ("claude-opus-5-5", "us.anthropic.claude-opus-5-5"),
        ("gpt-6-astra", "us.openai.gpt-6-astra"),
        ("gpt-6-1-sol", "us.openai.gpt-6.1-sol"),
        ("qwen3-235b", "qwen.qwen3-235b-a22b-2507-v1:0"),
        ("gpt-oss-120b", "openai.gpt-oss-120b-1:0"),
    ],
)
def test_exact_profile_and_model_ids_remain_distinct(key: str, expected: str) -> None:
    assert get_model(key).model_id == expected


def test_google_transport_and_meta_streaming_tool_exception_are_explicit() -> None:
    google = get_model("gemma-4-31b")
    assert google.transport == "mantle_chat"
    assert google.model_id == "google.gemma-4-31b"
    assert "no Converse support" in google.eligibility_note
    assert "parallel tool calls are unsupported" in google.eligibility_note
    meta = get_model("llama-4-maverick")
    assert meta.transport == "converse" and not meta.tool_streaming
    assert "non-streaming Converse" in meta.eligibility_note


def test_foundation_arns_do_not_invent_account_or_profile_wildcards() -> None:
    model = get_model("claude-sonnet-5-5")
    assert model.foundation_model_arns("us-west-2") == (
        "arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-sonnet-5-5",
    )
    assert model.foundation_model_arns("us-east-1") == (
        "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-5-5",
    )
    with pytest.raises(ValueError, match="concrete AWS Region"):
        model.foundation_model_arns("*")


def test_mantle_does_not_invent_runtime_foundation_model_permissions() -> None:
    with pytest.raises(ValueError, match="Mantle requires project authorization"):
        get_model("gemma-4-31b").foundation_model_arns("us-west-2")


@pytest.mark.parametrize("key", ["not-configured", "us.openai.gpt-6-astra", "../profile"])
def test_unknown_or_raw_provider_ids_are_not_catalog_aliases(key: str) -> None:
    with pytest.raises(ValueError, match="not in the reviewed"):
        get_model(key)
