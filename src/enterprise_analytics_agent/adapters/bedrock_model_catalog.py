"""Documented Bedrock choices, independent of account access or live approval.

This catalog is static data. Importing or reading it creates no AWS session and
does not discover permissions, subscribe to a model, or enable a live backend.
Source-region support is deliberately limited to the reviewed Oregon scope.
"""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

type ModelIdentifier = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9.-]*(?::[0-9]+)?$", max_length=2048)
]

UNVERIFIED_ACCESS = (
    "Catalog metadata does not establish account access, effective permissions, "
    "quota or current live acceptance."
)


class ModelSpec(BaseModel):
    """Trusted model metadata; it never supplies runtime authorization context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")]
    label: Annotated[str, Field(min_length=1, max_length=100)]
    provider: Annotated[str, Field(min_length=1, max_length=100)]
    model_id: ModelIdentifier
    transport: Literal["converse", "mantle_chat"]
    temperature_supported: bool
    reference_url: Annotated[
        str,
        Field(
            pattern=r"^https://docs\.aws\.amazon\.com/bedrock/latest/userguide/[a-z0-9-]+\.html$"
        ),
    ]
    regions: tuple[str, ...] = ("us-west-2",)
    model_resource_ids: Annotated[tuple[ModelIdentifier, ...], Field(min_length=1)]
    tool_streaming: bool
    eligibility_note: str = UNVERIFIED_ACCESS

    def foundation_model_arns(self, region: str) -> tuple[str, ...]:
        """Render exact foundation resources, including explicitly reviewed CRIS destinations.

        Profile permissions are a separate account-scoped resource. This helper
        does not invent a profile ARN or grant wildcard access to any Region.
        """
        if self.transport == "mantle_chat":
            raise ValueError(
                "Mantle requires project authorization; foundation-model ARNs do not "
                "authorize this transport."
            )
        if re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-[0-9]+", region) is None or region.startswith(
            ("us-gov-", "cn-")
        ):
            raise ValueError("A concrete AWS Region is required.")
        return tuple(
            f"arn:aws:bedrock:{region}::foundation-model/{identifier}"
            for identifier in self.model_resource_ids
        )


def _spec(
    key: str,
    label: str,
    provider: str,
    model_id: str,
    resource_id: str,
    card: str,
    *,
    temperature_supported: bool = True,
    transport: Literal["converse", "mantle_chat"] = "converse",
    tool_streaming: bool = True,
    note: str = "",
) -> ModelSpec:
    return ModelSpec(
        key=key,
        label=label,
        provider=provider,
        model_id=model_id,
        model_resource_ids=(resource_id,),
        reference_url=f"https://docs.aws.amazon.com/bedrock/latest/userguide/{card}.html",
        transport=transport,
        temperature_supported=temperature_supported,
        tool_streaming=tool_streaming,
        eligibility_note=f"{UNVERIFIED_ACCESS} {note}".strip(),
    )


# IDs and transport restrictions were checked against the linked official cards.
# A recommendation for analytics still requires independent authored evaluations;
# provider descriptions do not establish a universally best model.
BEDROCK_MODELS: tuple[ModelSpec, ...] = (
    _spec(
        "nova-lite",
        "Amazon Nova Lite",
        "Amazon",
        "us.amazon.nova-lite-v1:0",
        "amazon.nova-lite-v1:0",
        "model-card-amazon-nova-lite",
        note="Retains the accepted baseline; using another model needs its own approval.",
    ),
    _spec(
        "claude-sonnet-5-5",
        "Claude Sonnet 5.5",
        "Anthropic",
        "us.anthropic.claude-sonnet-5-5",
        "anthropic.claude-sonnet-5-5",
        "model-card-anthropic-claude-sonnet-5-5",
        temperature_supported=False,
        note="Uses US cross-Region inference. Preserve private reasoning blocks internally.",
    ),
    _spec(
        "claude-opus-5-5",
        "Claude Opus 5.5",
        "Anthropic",
        "us.anthropic.claude-opus-5-5",
        "anthropic.claude-opus-5-5",
        "model-card-anthropic-claude-opus-5-5",
        temperature_supported=False,
        note="Uses US cross-Region inference. Adaptive thinking remains provider-managed.",
    ),
    _spec(
        "gpt-6-astra",
        "GPT-6 Astra",
        "OpenAI",
        "us.openai.gpt-6-astra",
        "openai.gpt-6-astra",
        "model-card-openai-gpt-6-astra",
        temperature_supported=False,
        note="Bedrock Runtime US profile; no direct OpenAI API account is used.",
    ),
    _spec(
        "gpt-6-1-sol",
        "GPT-6.1 Sol",
        "OpenAI",
        "us.openai.gpt-6.1-sol",
        "openai.gpt-6.1-sol",
        "model-card-openai-gpt-6-1-sol",
        temperature_supported=False,
        note="Bedrock Runtime US profile; no direct OpenAI API account is used.",
    ),
    _spec(
        "gemma-4-31b",
        "Gemma 4 31B",
        "Google",
        "google.gemma-4-31b",
        "google.gemma-4-31b",
        "model-card-google-gemma-4-31b",
        transport="mantle_chat",
        note=(
            "Gemma, not Gemini. Requires Bedrock Mantle /openai/v1; no Converse support. "
            "Request one tool at a time; parallel tool calls are unsupported."
        ),
    ),
    _spec(
        "llama-4-maverick",
        "Llama 4 Maverick",
        "Meta",
        "us.meta.llama4-maverick-17b-instruct-v1:0",
        "meta.llama4-maverick-17b-instruct-v1:0",
        "model-card-meta-llama-4-maverick-17b-instruct",
        tool_streaming=False,
        note=(
            "US cross-Region inference. Tool use requires non-streaming Converse; "
            "tool-free response streaming is supported."
        ),
    ),
    _spec(
        "deepseek-v3-2",
        "DeepSeek V3.2",
        "DeepSeek",
        "deepseek.v3.2",
        "deepseek.v3.2",
        "model-card-deepseek-deepseek-v3-2",
    ),
    _spec(
        "qwen3-235b",
        "Qwen3 235B A22B 2507",
        "Qwen",
        "qwen.qwen3-235b-a22b-2507-v1:0",
        "qwen.qwen3-235b-a22b-2507-v1:0",
        "model-card-qwen-qwen3-235b-a22b-2507",
    ),
    _spec(
        "mistral-large-3",
        "Mistral Large 3",
        "Mistral AI",
        "mistral.mistral-large-3-675b-instruct",
        "mistral.mistral-large-3-675b-instruct",
        "model-card-mistral-ai-mistral-large-3",
    ),
    _spec(
        "gpt-oss-120b",
        "GPT-OSS 120B",
        "OpenAI",
        "openai.gpt-oss-120b-1:0",
        "openai.gpt-oss-120b-1:0",
        "model-card-openai-gpt-oss-120b",
        note="Open-source baseline, distinct from the frontier GPT model choices.",
    ),
)


def model_catalog() -> tuple[ModelSpec, ...]:
    """Return documented choices without discovering or enabling AWS access."""
    return BEDROCK_MODELS


def get_model(key: str) -> ModelSpec:
    """Resolve only a trusted catalog alias; model IDs are not browser overrides."""
    for model in BEDROCK_MODELS:
        if model.key == key:
            return model
    raise ValueError("The model key is not in the reviewed Bedrock catalog.")
