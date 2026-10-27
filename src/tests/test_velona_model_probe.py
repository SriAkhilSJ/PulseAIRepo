from __future__ import annotations

import json
import re

from scripts import probe_velona_models as probe_module


class _FakeProbe(probe_module.VelonaModelProbe):
    def _request(self, body):
        messages = body["messages"]
        if body.get("tools"):
            prompt = messages[0]["content"]
            nonce = re.search(r"nonce '([^']+)'", prompt).group(1)
            return (
                {
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_test",
                                        "type": "function",
                                        "function": {
                                            "name": "report_agent_core_probe",
                                            "arguments": json.dumps(
                                                {"nonce": nonce, "status": "ready"}
                                            ),
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 30,
                        "completion_tokens": 8,
                        "total_tokens": 38,
                        "provider_private": "must-not-survive",
                    },
                },
                0.01,
            )
        if messages[-1]["role"] == "tool":
            receipt = json.loads(messages[-1]["content"])["receipt"]
            content = receipt
        else:
            content = messages[0]["content"].rsplit(": ", 1)[-1]
        return (
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": content},
                    }
                ],
                "usage": {"input_tokens": 4, "output_tokens": 2},
            },
            0.01,
        )


def _probe(api_key="test-secret-value"):
    return _FakeProbe(
        base_url="https://velona.example/v1",
        api_key=api_key,
        main_model="z-ai/glm-5.3-flash",
        aux_model="qwen/qwen3.7-flash",
        timeout=1,
    )


def test_probe_exercises_main_tools_replay_and_aux_without_response_text():
    receipt = _probe().run()

    assert receipt["status"] == "passed"
    assert [phase["name"] for phase in receipt["phases"]] == [
        "main_basic",
        "main_forced_tool_call",
        "main_tool_result_replay",
        "aux_basic",
    ]
    assert all(phase["status"] == "passed" for phase in receipt["phases"])
    encoded = json.dumps(receipt)
    assert "must-not-survive" not in encoded
    assert "test-secret-value" not in encoded
    assert "response_sha256" in encoded


def test_basic_probe_retries_one_transient_read_timeout():
    instance = _probe()
    successful_request = instance._request
    calls = 0

    def flaky_request(body):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("transient read timeout")
        return successful_request(body)

    instance._request = flaky_request
    evidence = instance._main_basic()

    assert evidence["sentinel_preserved"] is True
    assert evidence["attempts"] == 2
    assert calls == 2


def test_failed_phases_redact_the_exact_api_key():
    key = "secret-api-key-should-never-appear"
    instance = _probe(api_key=key)

    def fail(_body):
        raise RuntimeError(f"provider rejected Bearer {key}")

    instance._request = fail
    receipt = instance.run()
    encoded = json.dumps(receipt)

    assert receipt["status"] == "failed"
    assert key not in encoded
    assert "Bearer [REDACTED]" in encoded


def test_safe_usage_keeps_counts_only():
    assert probe_module._safe_usage(
        {
            "prompt_tokens": 7,
            "completion_tokens": 3,
            "total_tokens": 10,
            "cost": 99,
            "private": "value",
        }
    ) == {
        "prompt_tokens": 7,
        "completion_tokens": 3,
        "total_tokens": 10,
    }


def test_phase_annotations_publish_bounded_safe_evidence(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    receipt = _probe().run()

    probe_module._publish_phase_annotations(receipt)

    output = capsys.readouterr().out
    assert output.count("::notice title=Velona probe:") == 4
    assert "main_forced_tool_call" in output
    assert "test-secret-value" not in output
    assert "must-not-survive" not in output
