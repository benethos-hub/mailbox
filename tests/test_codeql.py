"""The CodeQL analysis: the wiring of the codeql job in ci.yml and of codeql.yml.

The analysis runs through the organisation's workflow, which proves itself
there. What can go wrong here is the call: a language left out, the two calls
drifting apart, a permission beyond the upload, a weekly run that is not
weekly, or a second category that would count every finding twice. The pin of
every action that is not the organisation's is held here as well.
"""

from __future__ import annotations

import re

from .publish_helpers import ROOT

WORKFLOWS = ROOT / ".github" / "workflows"
CI = (WORKFLOWS / "ci.yml").read_text("utf-8")
WEEKLY = (WORKFLOWS / "codeql.yml").read_text("utf-8")
CALL = "uses: benethos-hub/.github/.github/workflows/codeql.yml@main"
ORG = "benethos-hub/.github/"
# The scanners of ci.yml that upload to code scanning: codeql here and
# dockerfile-lint, whose test is test_dockerfile_lint.py.
SCANNERS = 2


def _job(workflow: str, name: str) -> str:
    return workflow.split(f"\n  {name}:\n", 1)[1].split("\n\n  ", 1)[0].rstrip()


def test_the_ci_job_calls_the_organisations_workflow_for_all_our_code() -> None:
    job = _job(CI, "codeql")
    assert CALL in job
    assert "languages: python,javascript-typescript,actions" in job


def test_the_weekly_workflow_makes_the_same_call() -> None:
    """One analysis in two places, so a change to one is a change to both."""
    assert _job(WEEKLY, "codeql") == _job(CI, "codeql")


def test_the_calls_name_the_configuration_of_this_repository() -> None:
    """A path that does not exist would stop the analysis on every run."""
    named = re.search(r"config-file: (\S+)", _job(CI, "codeql"))
    assert named is not None
    assert (ROOT / named.group(1)).is_file()


def test_the_weekly_run_is_weekly_and_by_hand_only() -> None:
    on = WEEKLY.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    assert re.search(r'cron: "\d+ \d+ \* \* [0-6]"', on), "one weekday, once"
    assert "workflow_dispatch:" in on
    assert "push" not in on
    assert "pull_request" not in on


def test_the_upload_permission_is_granted_to_the_scanners_and_nowhere_else() -> None:
    assert "security-events: write" in _job(CI, "codeql")
    assert CI.count("security-events: write") == SCANNERS
    assert WEEKLY.count("security-events: write") == 1
    assert "contents: write" not in WEEKLY


def test_the_two_runs_share_the_default_category() -> None:
    """A category of their own would file the same findings twice."""
    assert "category:" not in _job(CI, "codeql")
    assert "category:" not in WEEKLY


def test_every_action_that_is_not_the_organisations_is_pinned_to_a_commit() -> None:
    """The organisation's own are followed at main."""
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for line in path.read_text("utf-8").splitlines():
            uses = re.search(r"uses: (\S+)", line)
            if uses is None or uses.group(1).startswith(ORG):
                continue
            assert re.search(r"@[0-9a-f]{40} # v\d", line), (
                f"{path.name}: {line.strip()}"
            )
