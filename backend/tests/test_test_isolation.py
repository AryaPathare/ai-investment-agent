"""Tests that the test suite is actually isolated from the developer's machine.

The suite advertises "no network, no API key, fully deterministic" and the
README repeats it. That claim was false for five tests: `conftest` set
GROQ_API_KEY and NEWS_API_KEY but not FMP_API_KEY, so those tests quietly read
the developer's real `.env`, and on any machine without one they failed with
"FMP_API_KEY is not set" instead of the error they were asserting on.

Nothing revealed it for weeks, because every run happened in the one place the
file existed. It surfaced the first time the suite ran on a clean clone.

A green suite that depends on an untracked file is not evidence the code works;
it is evidence the code works HERE.
"""

import re

import pytest

from backend import config
from backend.config import PROJECT_ROOT


def _credential_fields() -> list[str]:
    """Every setting config.py reads as a secret."""
    return [
        name
        for name, field in config.Settings.model_fields.items()
        if name.endswith("_api_key")
    ]


def test_conftest_sets_every_credential_config_can_read():
    """THE regression guard.

    Adding a provider to config.py without adding it here reintroduces exactly
    the failure above: green locally, broken anywhere else.
    """
    conftest = (PROJECT_ROOT / "conftest.py").read_text(encoding="utf-8")
    set_here = set(re.findall(r'monkeypatch\.setenv\("([A-Z_]+)"', conftest))

    missing = [
        name.upper() for name in _credential_fields()
        if name.upper() not in set_here
    ]
    assert not missing, (
        f"config.py reads {missing} but tests/conftest.py never sets it, so "
        "these tests fall through to a real .env and pass only on a machine "
        "that has one"
    )


@pytest.mark.parametrize("name", _credential_fields())
def test_each_credential_is_a_dummy_during_tests(name):
    """Not merely set - set to something that cannot possibly be real.

    A test that reached the network with a live key would spend quota and
    could pass or fail for reasons unrelated to the code.
    """
    value = getattr(config.get_settings(), name)
    assert value is not None, f"{name} should be set during tests"
    assert "test" in value.get_secret_value().lower(), (
        f"{name} does not look like a dummy value; a real key may be leaking "
        "into the test environment"
    )


def test_the_suite_does_not_depend_on_a_dotenv_file():
    """The .env is untracked, so anything depending on it fails for everyone
    except the person who wrote it."""
    assert not (PROJECT_ROOT / ".env").is_dir()
    # The fixture must win over the file, whether or not the file exists.
    assert config.get_settings().groq_api_key.get_secret_value() == "test-key-never-used"


# --- Anything that writes into .state/ ---------------------------------------
#
# Found twice now. `checkpoints.DB_PATH` was redirected when the checkpoint
# database was built, because the risk was obvious: it holds runs a person has
# not finished. `web/quota.py` then added a second file there and nothing
# redirected it, so the suite wrote twenty-one runs into the ledger that decides
# how many runs the site believes it has left - and it was noticed by reading
# the file, not by anything failing.
#
# A third writer should not have to be found that way.


def _state_paths() -> dict[str, str]:
    """Every module-level constant pointing into .state/, as module -> name."""
    found = {}
    for source in PROJECT_ROOT.rglob("*.py"):
        if any(part in {".venv", "tests", "__pycache__"} for part in source.parts):
            continue
        for name in re.findall(
            r'^([A-Z_]+)\s*=\s*PROJECT_ROOT\s*/\s*"\.state"', 
            source.read_text(encoding="utf-8"),
            re.MULTILINE,
        ):
            module = str(source.relative_to(PROJECT_ROOT).with_suffix("")).replace(
                "\\", "."
            ).replace("/", ".")
            found[f"{module}.{name}"] = name
    return found


def test_every_state_file_is_redirected_during_tests():
    """THE regression guard, and the reason this section exists.

    A path still pointing inside the real .state/ while the suite runs means
    some test is writing to a file a real run depends on. The failure is silent
    both ways: the test passes, and the damage shows up later as a wrong number
    or a lost run.
    """
    import importlib

    live = []
    for dotted in _state_paths():
        module_name, _, attribute = dotted.rpartition(".")
        value = getattr(importlib.import_module(module_name), attribute)
        if PROJECT_ROOT in value.parents:
            live.append(dotted)

    assert not live, (
        f"{live} still point inside the real .state/ during tests. Add an "
        f"autouse fixture in conftest.py redirecting each at tmp_path."
    )


def test_the_guard_above_is_actually_looking_at_something():
    """A guard that found nothing to check would pass forever and prove nothing.

    Both known writers must be visible to it, so a rename that hides one from
    the regex fails here rather than quietly reducing the guard to a no-op.
    """
    found = set(_state_paths())

    assert "backend.checkpoints.DB_PATH" in found
    assert "frontend.quota.LEDGER" in found
