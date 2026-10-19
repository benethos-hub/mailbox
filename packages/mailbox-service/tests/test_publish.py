"""The publish workflow, .github/workflows/publish.yml.

The four packages go to PyPI through the organisation's action
publish/pypi, one job each, in the order of their dependencies, and a
manual run tries all four without uploading.
"""

from __future__ import annotations

import re

from .publish_helpers import (
    PACKAGES,
    ROOT,
    module_of,
    project_of,
    workflow_job,
    workspace_needs,
)

SERVICE, CLIENT, MCP, COMMON = PACKAGES


def _wheel_contains(module: str) -> str:
    """What the action publish/pypi checks in a package's wheel: the PEP
    561 marker and the license text."""
    return (
        "          wheel-contains: |\n"
        f"            {module}/py.typed\n"
        f"            {module}-{{version}}.dist-info/licenses/LICENSE\n"
    )


def _publish_jobs() -> dict[str, dict[str, object]]:
    """The PyPI upload jobs of publish.yml by package: the job's name,
    the jobs it waits for, its environment and what its wheel must carry."""
    text = (ROOT / ".github" / "workflows" / "publish.yml").read_text("utf-8")
    jobs: dict[str, dict[str, object]] = {}
    for job, body in re.findall(r"^  (pypi-\S+):\n((?:    .*\n|\n)+)", text, re.M):
        if job == "pypi-trial":
            continue
        package = re.search(r"^\s+package: (\S+)$", body, re.M)
        environment = re.search(r"^      name: (\S+)$", body, re.M)
        needs = re.search(r"^    needs: \[(.*)\]$", body, re.M)
        assert package and environment and needs, job
        assert "if: github.event_name == 'release'" in body, job
        jobs[package.group(1)] = {
            "job": job,
            "body": body,
            "environment": environment.group(1),
            "needs": {n.strip() for n in needs.group(1).split(",")},
        }
    return jobs


def test_every_package_is_published() -> None:
    """publish.yml uploads each package to PyPI in a job of its own, on a
    release only: its name, what the wheel must carry, and an environment
    of its own, named after the package, since PyPI takes a pending
    publisher for one project only."""
    jobs = _publish_jobs()
    assert set(jobs) == {str(project_of(p)["name"]) for p in PACKAGES}
    for package in PACKAGES:
        name = str(project_of(package)["name"])
        assert _wheel_contains(module_of(package)) in str(jobs[name]["body"])
        assert jobs[name]["environment"] == f"pypi-{name}"


def test_a_manual_run_tries_every_package() -> None:
    """pypi-trial builds and checks each package on a manual run, without
    an environment and without an OIDC token."""
    trial = workflow_job("pypi-trial")
    tried = dict(re.findall(r"^ +- package: (\S+)\n +module: (\S+)$", trial, re.M))
    assert tried == {str(project_of(p)["name"]): module_of(p) for p in PACKAGES}
    assert "dry-run: true" in trial
    assert _wheel_contains("${{ matrix.module }}") in trial
    assert "environment:" not in trial and "id-token" not in trial


def test_a_job_with_rights_of_its_own_still_reads_the_repository() -> None:
    """The permissions of a job replace the workflow's. Each job that
    names its own keeps ``contents: read``, which its checkout needs once
    the repository is private, or ``contents: write``, which reads too."""
    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        text = workflow.read_text("utf-8")
        blocks = re.findall(r"^    permissions:\n((?:      .*\n)+)", text, re.M)
        for block in blocks:
            assert re.search(r"contents: (read|write)", block), workflow.name


def test_a_package_is_published_after_those_it_needs() -> None:
    """A package that reaches PyPI before one it pins cannot be
    installed. Each job waits for the release gate and for the jobs of
    the packages it needs. The client waits for the common package too,
    so it may come to need it without a change here."""
    jobs = _publish_jobs()
    for package in PACKAGES:
        name = str(project_of(package)["name"])
        needed = workspace_needs(package)
        if package == CLIENT:
            needed.add(str(project_of(COMMON)["name"]))
        wanted = {"ci-passed"} | {str(jobs[n]["job"]) for n in needed}
        assert jobs[name]["needs"] == wanted, name
