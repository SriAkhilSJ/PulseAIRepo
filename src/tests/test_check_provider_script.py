"""CrusorAI — the provider readiness check (``scripts/check_provider.py``).

The script itself is a diagnostic, so the interesting things to pin are not its output
format but two properties that are easy to lose later:

* **a key is never printed**, in part or in whole — the check runs in terminals, in
  pasted evidence, and in CI logs, and the last four characters are the most a doctor
  should ever reveal;
* **the provider list cannot drift from the factory**. If a provider is added to
  ``get_llm`` and not to the doctor, the doctor starts reporting "not one of them" for a
  perfectly valid configuration — a diagnostic that lies is worse than none.

The module is imported rather than executed, so this lane needs neither a network nor the
provider SDKs (``dotenv`` and the SDKs are imported inside ``main``, not at module level).
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_provider.py"


@pytest.fixture(scope="module")
def doctor():
    spec = importlib.util.spec_from_file_location("check_provider", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_redaction_keeps_the_tail_and_drops_the_secret(doctor) -> None:
    secret = "gsk_verysecretvalue1234"
    shown = doctor.redact(secret)
    assert "verysecret" not in shown, shown
    assert secret not in shown
    assert shown.startswith("set, ..."), shown
    assert "1234" in shown, "the tail is there to tell two keys apart"
    assert "23 chars" in shown, "the length is the other fingerprint, and it is not secret"


def test_redaction_is_honest_about_absence_and_short_values(doctor) -> None:
    assert doctor.redact(None) == "(not set)"
    assert doctor.redact("") == "(not set)"
    # A 4-char value has no tail worth showing: revealing it would reveal the whole key.
    short = doctor.redact("1234")
    assert "1234" not in short.replace("(short!)", ""), short


def test_the_doctor_knows_every_provider_the_factory_can_build(doctor) -> None:
    factory_source = (REPO_ROOT / "src" / "llm" / "factory.py").read_text(encoding="utf-8")
    dispatched = set(re.findall(r'provider == "([a-z]+)"', factory_source))
    assert dispatched, "the factory dispatch could not be read — this pin is not verifying anything"

    covered = set(doctor.KEY_VARS)
    assert covered == dispatched, (
        f"the doctor and the factory disagree: only in factory={sorted(dispatched - covered)}, "
        f"only in doctor={sorted(covered - dispatched)}"
    )


def test_every_provider_has_a_key_variable_to_read(doctor) -> None:
    for provider, (key_var, url_var) in doctor.KEY_VARS.items():
        assert key_var and isinstance(key_var, str), provider
        # GROQ_API_KEY, CUSTOM_API_KEY, CRUSORAI_CHEAP_API_KEY … but never a blank slot.
        assert key_var.isupper() and "_" in key_var, key_var
        assert url_var is None or url_var.isupper(), url_var
