from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yanhai.providers import (  # noqa: E402
    ProviderConfig,
    ProviderError,
    create_provider,
    list_providers,
)


class ProviderTests(unittest.TestCase):
    def test_four_remote_providers_and_mock_are_available(self) -> None:
        provider_ids = {item["id"] for item in list_providers()}
        self.assertEqual(
            {
                "mock",
                "deepseek",
                "free-deepseek",
                "openai",
                "anthropic",
                "kimi",
                "zhipu",
                "qwen",
            },
            provider_ids,
        )

    def test_api_key_is_not_exposed_by_public_config_or_repr(self) -> None:
        secret = "sk-test-secret-value"
        config = ProviderConfig.from_payload(
            {
                "provider": "openai",
                "model": "gpt-5.6-terra",
                "api_key": secret,
            }
        )
        self.assertNotIn(secret, repr(config))
        self.assertNotIn("api_key", config.public_dict())

    def test_remote_provider_requires_api_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "API Key"):
            ProviderConfig.from_payload({"provider": "anthropic"})

    def test_openai_compatible_json_request_and_usage_are_normalised(self) -> None:
        captured: dict[str, Any] = {}

        def transport(
            url: str,
            headers: dict[str, str],
            payload: dict[str, Any],
            timeout: float,
        ) -> tuple[dict[str, Any], dict[str, str]]:
            captured.update(
                {
                    "url": url,
                    "headers": headers,
                    "payload": payload,
                    "timeout": timeout,
                }
            )
            return (
                {
                    "id": "req_1",
                    "model": "deepseek-v4-flash",
                    "choices": [
                        {"message": {"content": '{"status":"ok"}'}}
                    ],
                    "usage": {
                        "prompt_tokens": 12,
                        "completion_tokens": 3,
                        "total_tokens": 15,
                    },
                },
                {"x-request-id": "request-header"},
            )

        config = ProviderConfig.from_payload(
            {
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "api_key": "test-key",
            }
        )
        provider = create_provider(config, transport)
        data, response = provider.complete_json(
            "system",
            "user",
            schema_name="status",
            schema={
                "type": "object",
                "properties": {"status": {"type": "string"}},
                "required": ["status"],
            },
        )
        self.assertEqual({"status": "ok"}, data)
        self.assertEqual(15, response.usage["total_tokens"])
        self.assertEqual(
            {"type": "json_object"},
            captured["payload"]["response_format"],
        )
        self.assertEqual(
            {"type": "disabled"},
            captured["payload"]["thinking"],
        )
        self.assertEqual(0, captured["payload"]["temperature"])
        self.assertNotIn("test-key", str(response.public_dict()))

    def test_truncated_json_is_retried_and_usage_is_aggregated(self) -> None:
        payloads: list[dict[str, Any]] = []

        def transport(
            url: str,
            headers: dict[str, str],
            payload: dict[str, Any],
            timeout: float,
        ) -> tuple[dict[str, Any], dict[str, str]]:
            payloads.append(payload)
            if len(payloads) == 1:
                content = '{"status":"incomplete"'
                finish_reason = "length"
            else:
                content = '{"status":"ok"}'
                finish_reason = "stop"
            return (
                {
                    "id": f"req_{len(payloads)}",
                    "model": "deepseek-v4-flash",
                    "choices": [
                        {
                            "finish_reason": finish_reason,
                            "message": {"content": content},
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 20,
                        "total_tokens": 30,
                    },
                },
                {},
            )

        config = ProviderConfig.from_payload(
            {
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "api_key": "test-key",
            }
        )
        provider = create_provider(config, transport)
        provider_events: list[dict[str, Any]] = []
        provider.set_event_callback(provider_events.append)
        data, response = provider.complete_json(
            "system",
            "user",
            schema_name="status",
            schema={
                "type": "object",
                "properties": {"status": {"const": "ok"}},
                "required": ["status"],
            },
            max_tokens=5000,
        )

        self.assertEqual({"status": "ok"}, data)
        self.assertEqual(2, response.attempts)
        self.assertEqual("stop", response.finish_reason)
        self.assertEqual(60, response.usage["total_tokens"])
        self.assertEqual(7500, payloads[1]["max_tokens"])
        self.assertEqual("structured_retry", provider_events[0]["kind"])
        self.assertEqual("status", provider_events[0]["schema_name"])

    def test_empty_json_content_is_retried_without_stringifying_none(self) -> None:
        attempts = 0

        def transport(
            url: str,
            headers: dict[str, str],
            payload: dict[str, Any],
            timeout: float,
        ) -> tuple[dict[str, Any], dict[str, str]]:
            nonlocal attempts
            attempts += 1
            return (
                {
                    "id": f"req_{attempts}",
                    "model": "deepseek-v4-flash",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": None if attempts == 1 else '{"status":"ok"}'
                            },
                        }
                    ],
                    "usage": {},
                },
                {},
            )

        config = ProviderConfig.from_payload(
            {
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "api_key": "test-key",
            }
        )
        data, response = create_provider(config, transport).complete_json(
            "system",
            "user",
            schema_name="status",
            schema={
                "type": "object",
                "properties": {"status": {"type": "string"}},
                "required": ["status"],
            },
        )

        self.assertEqual({"status": "ok"}, data)
        self.assertEqual(2, response.attempts)

    def test_json_schema_mismatch_is_rejected_after_retry(self) -> None:
        def transport(
            url: str,
            headers: dict[str, str],
            payload: dict[str, Any],
            timeout: float,
        ) -> tuple[dict[str, Any], dict[str, str]]:
            return (
                {
                    "model": "deepseek-v4-flash",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": '{"status":42}'},
                        }
                    ],
                    "usage": {},
                },
                {},
            )

        config = ProviderConfig.from_payload(
            {
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "api_key": "test-key",
            }
        )
        with self.assertRaisesRegex(ProviderError, "不符合 status Schema"):
            create_provider(config, transport).complete_json(
                "system",
                "user",
                schema_name="status",
                schema={
                    "type": "object",
                    "properties": {"status": {"type": "string"}},
                    "required": ["status"],
                },
            )

    def test_provider_error_redacts_exact_key(self) -> None:
        def transport(
            url: str,
            headers: dict[str, str],
            payload: dict[str, Any],
            timeout: float,
        ) -> tuple[dict[str, Any], dict[str, str]]:
            raise ProviderError("invalid key test-secret")

        config = ProviderConfig.from_payload(
            {
                "provider": "kimi",
                "model": "kimi-k2.6",
                "api_key": "test-secret",
            }
        )
        with self.assertRaisesRegex(ProviderError, r"\[REDACTED\]"):
            create_provider(config, transport).test_connection()

    def test_openai_responses_text_is_extracted(self) -> None:
        def transport(
            url: str,
            headers: dict[str, str],
            payload: dict[str, Any],
            timeout: float,
        ) -> tuple[dict[str, Any], dict[str, str]]:
            return (
                {
                    "id": "resp_1",
                    "model": "gpt-5.6-terra",
                    "output": [
                        {
                            "content": [
                                {"type": "output_text", "text": "OK"}
                            ]
                        }
                    ],
                    "usage": {
                        "input_tokens": 4,
                        "output_tokens": 1,
                        "total_tokens": 5,
                    },
                },
                {"x-request-id": "openai-request"},
            )

        config = ProviderConfig.from_payload(
            {
                "provider": "openai",
                "model": "gpt-5.6-terra",
                "api_key": "test-key",
            }
        )
        response = create_provider(config, transport).test_connection()
        self.assertEqual("OK", response.content)
        self.assertEqual("openai-request", response.request_id)

    def test_anthropic_messages_text_is_extracted(self) -> None:
        def transport(
            url: str,
            headers: dict[str, str],
            payload: dict[str, Any],
            timeout: float,
        ) -> tuple[dict[str, Any], dict[str, str]]:
            self.assertEqual("2023-06-01", headers["Anthropic-Version"])
            return (
                {
                    "id": "msg_1",
                    "model": "claude-sonnet-5",
                    "content": [{"type": "text", "text": "OK"}],
                    "usage": {"input_tokens": 5, "output_tokens": 1},
                },
                {"request-id": "anthropic-request"},
            )

        config = ProviderConfig.from_payload(
            {
                "provider": "anthropic",
                "model": "claude-sonnet-5",
                "api_key": "test-key",
            }
        )
        response = create_provider(config, transport).test_connection()
        self.assertEqual("OK", response.content)
        self.assertEqual(6, response.usage["total_tokens"])


if __name__ == "__main__":
    unittest.main()
