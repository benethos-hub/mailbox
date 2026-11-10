"""The daily freshness check: the wiring of freshness.yml.

The check runs through the organisation's workflow and actions, which prove
themselves there. What can go wrong here is the call: a trigger that is not
a schedule, a permission beyond issues, an artifact the report does not
expect, or a published package the index job does not install.
"""

from __future__ import annotations

import json
import re

import pytest

from . import installed_check
from .publish_helpers import PACKAGES, ROOT, project_of

WORKFLOW = (ROOT / ".github" / "workflows" / "freshness.yml").read_text("utf-8")
ORG = "benethos-hub/.github/"


def _step(name: str) -> str:
    return WORKFLOW.split(f"- name: {name}\n", 1)[1].split("\n      - ", 1)[0]


def _job(name: str) -> str:
    after = WORKFLOW.split(f"\n  {name}:\n", 1)[1]
    return re.split(r"\n\n  (?! )", after, maxsplit=1)[0]


def test_it_runs_on_a_schedule_after_publish_and_by_hand_only() -> None:
    on = WORKFLOW.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    assert "schedule:" in on
    assert "workflow_run:" in on
    assert "workflow_dispatch:" in on
    assert "push" not in on
    assert "pull_request" not in on


# A run of Publish here, by a release or by hand. A workflow of that name
# in a fork's pull request completes as well and would start a run.
OURS = (
    "github.event_name != 'workflow_run' || "
    "(github.event.workflow_run.head_repository.full_name == github.repository "
    "&& (github.event.workflow_run.event == 'release' "
    "|| github.event.workflow_run.event == 'workflow_dispatch'))"
)


@pytest.mark.parametrize("job", ["newest", "npm-outdated", "npm-audit", "freshness"])
def test_each_job_runs_after_a_publish_of_this_repository_only(job: str) -> None:
    found = re.search(r"^    if: >-\n((?:      .*\n)+)", _job(job) + "\n", re.M)
    assert found is not None, f"{job} has no condition"
    assert OURS in " ".join(found.group(1).split())


def test_the_run_after_publish_names_the_workflow_as_it_reads() -> None:
    """A trigger with another name never fires, and nothing says so."""
    publish = (ROOT / ".github" / "workflows" / "publish.yml").read_text("utf-8")
    name = publish.split("\n", 1)[0].removeprefix("name: ")
    assert f"workflows: [{name}]\n    types: [completed]\n" in WORKFLOW


def test_the_newest_job_is_the_organisations_with_the_check() -> None:
    step = _step("Test the newest versions allowed")
    assert f"uses: {ORG}actions/python/freshness-newest@main" in step
    assert "check: uv run --frozen python tests/installed_check.py" in step


def test_the_artifact_is_named_as_the_report_expects() -> None:
    """freshness-<job>, named in extra-jobs, from the folder the action fills."""
    assert "findings: ${{ runner.temp }}/freshness/newest" in _step(
        "Test the newest versions allowed"
    )
    upload = _step("Leave the result for the report")
    assert "name: freshness-newest" in upload
    assert "path: ${{ runner.temp }}/freshness/newest" in upload


def test_the_report_is_the_organisations_and_knows_the_job() -> None:
    job = _job("freshness")
    assert f"uses: {ORG}.github/workflows/freshness.yml@main" in job
    assert "needs: [newest, npm-outdated, npm-audit]" in job
    assert "extra-jobs: newest npm-outdated npm-audit" in job
    dead = "if: >-\n      !cancelled() && ("
    assert dead in job, "a dead job is a line in the report"


@pytest.mark.parametrize(
    ("job", "action"),
    [("npm-outdated", "freshness-outdated"), ("npm-audit", "freshness-audit")],
)
def test_the_npm_jobs_read_the_lockfile_of_the_vendored_packages(
    job: str, action: str
) -> None:
    """The folder a job names must hold the lockfile, or the job fails daily."""
    steps = _job(job)
    assert f"uses: {ORG}actions/node/{action}@main" in steps
    found = re.search(r"directory: (\S+)", steps)
    assert found is not None
    assert (ROOT / found.group(1) / "package-lock.json").is_file()
    assert "persist-credentials: false" in steps
    assert "timeout-minutes:" in steps
    assert f"findings: ${{{{ runner.temp }}}}/freshness/{job}" in steps
    assert f"name: freshness-{job}" in steps
    assert f"path: ${{{{ runner.temp }}}}/freshness/{job}" in steps


def test_the_index_job_checks_every_published_package() -> None:
    job = _job("freshness")
    assert "index: true" in job
    assert "index-check: $FRESHNESS_PYTHON tests/installed_check.py" in job
    found = re.search(r"index-packages: '(.+)'", job)
    assert found is not None
    names = {str(project_of(package)["name"]) for package in PACKAGES}
    assert set(json.loads(found.group(1))) == names


def test_the_check_knows_every_published_package() -> None:
    names = {str(project_of(package)["name"]) for package in PACKAGES}
    assert set(installed_check.CHECKS) == names


def test_the_two_issues_have_titles_of_their_own() -> None:
    titles = re.findall(r"^\s+(?:issue-|alarm-)title: (.+)$", WORKFLOW, re.M)
    assert len(titles) == 2
    assert len(set(titles)) == 2


def test_it_can_write_issues_and_nothing_else() -> None:
    assert "contents: write" not in WORKFLOW
    assert WORKFLOW.count("issues: write") == 1
