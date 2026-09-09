"""Tests for the files that describe how this gets deployed.

A deployment file is otherwise only testable BY DEPLOYING, which is why the one
in this repository sat for a session asserting something that did nothing. It
said:

    pythonVersion: "3.14"

`pythonVersion` is not a key Render's blueprint spec defines. It was written on
the reasonable assumption that a blueprint pinning everything else would pin
this too, it was silently ignored, and nothing could have noticed - the suite
does not deploy, and the service had never been created. It happened to be
harmless only because Render's own default was already 3.14.

So these tests do the one thing that can be done without a deploy: check that
what the config CLAIMS agrees with the rest of the repository. They cannot
verify that Render honours any of it. That distinction is the point - a guard
whose limits are not stated gets trusted for more than it checks.

Read as plain text rather than parsed as YAML on purpose. PyYAML is present
here only as a transitive dependency of langchain and is absent from
requirements.txt, so importing it would make this file's fate depend on a
package the project does not declare.
"""

import re
from pathlib import Path

import pytest

from backend.config import PROJECT_ROOT

RENDER_YAML = PROJECT_ROOT / "render.yaml"
PROCFILE = PROJECT_ROOT / "Procfile"
PYTHON_VERSION_FILE = PROJECT_ROOT / ".python-version"
CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "tests.yml"


def _read(path: Path) -> str:
    assert path.exists(), f"{path.name} is missing"
    return path.read_text(encoding="utf-8")


def _settings(path: Path) -> str:
    """The file with its comments removed.

    Needed because the first draft of the `pythonVersion` guard below matched
    the word inside the comment EXPLAINING why not to use it, and went red on a
    correct file. A guard over a config has to read the config; prose that
    happens to quote a key is not the key being set.
    """
    lines = [line.split("#", 1)[0] for line in _read(path).splitlines()]
    return "\n".join(line for line in lines if line.strip())


def test_the_deployed_python_matches_the_tested_python():
    """The interpreter a visitor's run executes on is the one CI proved green.

    `.python-version` is one of exactly two mechanisms Render honours - the
    other being a fully qualified PYTHON_VERSION environment variable. The
    patch number is deliberately omitted so that this tracks the CI matrix,
    which also floats the patch. Pinning a patch in one place and not the other
    is how the deployed and the tested interpreter quietly diverge.
    """
    declared = _read(PYTHON_VERSION_FILE).strip()

    matrix = re.search(r'python-version:\s*\[\s*"([^"]+)"', _read(CI_WORKFLOW))
    assert matrix, "could not find the python-version matrix in the CI workflow"

    assert declared == matrix.group(1), (
        f".python-version says {declared!r} but CI runs {matrix.group(1)!r}. "
        "The deployed interpreter and the tested one must be the same."
    )


def test_the_python_version_is_not_set_by_a_key_render_ignores():
    """Regression guard, naming the real failure it came from.

    `pythonVersion:` looks exactly like a pin and is not one. Anything that
    reintroduces it - including a well-meaning tidy-up that moves the version
    back into render.yaml where it reads more naturally - should fail here
    rather than on a deploy nobody watches.
    """
    assert "pythonVersion" not in _settings(RENDER_YAML), (
        "render.yaml sets pythonVersion, which Render's blueprint spec does "
        "not define and silently ignores. Use .python-version instead."
    )


@pytest.mark.parametrize("path", [RENDER_YAML, PROCFILE])
def test_every_start_command_pins_one_worker(path):
    """One worker is a correctness constraint, not a performance choice.

    The queue that stops two runs writing to the same SQLite checkpoint file
    lives in a single process. Two workers means two queues, and both the
    runs-left counter and the "you are second in line" position would each be
    counting half the traffic.

    Stated in the command rather than left to a default, so that raising it is
    a deliberate act by somebody who has read why.
    """
    text = _read(path)
    commands = [line for line in text.splitlines() if "uvicorn" in line]
    assert commands, f"{path.name} names no uvicorn command"

    for command in commands:
        assert "--workers 1" in command, (
            f"{path.name} starts uvicorn without --workers 1: {command.strip()}"
        )


def test_the_health_check_path_is_a_real_route():
    """Render polls healthCheckPath to decide the service is up.

    A path that does not exist returns 404, which reads to the platform as a
    service that never became healthy - and the deploy fails with nothing
    obviously wrong in the application.
    """
    declared = re.search(r"healthCheckPath:\s*(\S+)", _settings(RENDER_YAML))
    assert declared, "render.yaml declares no healthCheckPath"

    from frontend.app import app

    routes = {getattr(route, "path", None) for route in app.routes}
    assert declared.group(1) in routes, (
        f"healthCheckPath {declared.group(1)!r} is not a route on the app. "
        f"Routes are {sorted(p for p in routes if p)}"
    )


@pytest.mark.parametrize("path", [RENDER_YAML, PROCFILE])
def test_every_start_command_names_an_importable_app(path):
    """`frontend.app:app` has to resolve, or the container starts and dies.

    Cheap to check and the exact failure a rename would cause: the module moves,
    every test still passes because the tests import it by name, and the only
    thing left pointing at the old path is the file nobody runs locally.
    """
    import importlib

    for reference in re.findall(r"([\w.]+):(\w+)\b", _read(path)):
        module_name, attribute = reference
        if not module_name.startswith("web"):
            continue
        module = importlib.import_module(module_name)
        assert hasattr(module, attribute), (
            f"{path.name} starts {module_name}:{attribute}, "
            f"but {module_name} has no attribute {attribute!r}"
        )
