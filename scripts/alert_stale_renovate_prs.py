"""Alert when a green Renovate PR waits too long for automerge."""

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone


MAX_WAIT = timedelta(hours=6)
ALERT_PREFIX = "Renovate automerge delayed for PR #"
VALID_SUCCESS = {"success", "neutral", "skipped"}
REQUIRED_CHECK = "validation / validation"
REQUIRED_STATUS = "infrastructure-validation"


def api(path: str, *, method: str = "GET", fields: dict[str, str] | None = None):
    command = ["gh", "api", "--method", method, path]
    for key, value in (fields or {}).items():
        command.extend(["-f", f"{key}={value}"])
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout) if result.stdout else None


def pages(path: str, *, key: str | None = None):
    page = 1
    while True:
        separator = "&" if "?" in path else "?"
        response = api(f"{path}{separator}per_page=100&page={page}")
        batch = response[key] if key else response
        yield from batch
        if len(batch) < 100:
            return
        page += 1


def timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def green_since(repo: str, sha: str) -> datetime | None:
    checks = list(pages(f"repos/{repo}/commits/{sha}/check-runs", key="check_runs"))
    statuses = api(f"repos/{repo}/commits/{sha}/status")["statuses"]
    if not checks or any(
        check["status"] != "completed" or check["conclusion"] not in VALID_SUCCESS
        for check in checks
    ):
        return None
    if any(status["state"] != "success" for status in statuses):
        return None
    if not any(
        check["name"] == REQUIRED_CHECK and check["conclusion"] == "success"
        for check in checks
    ):
        return None
    if not any(
        status["context"] == REQUIRED_STATUS and status["state"] == "success"
        for status in statuses
    ):
        return None
    completed = [timestamp(check["completed_at"]) for check in checks]
    completed.extend(timestamp(status["updated_at"]) for status in statuses)
    return max(completed)


def stale_pr(repo: str, pr: dict, now: datetime) -> datetime | None:
    if (
        pr["draft"]
        or pr["user"]["login"] not in {"renovate[bot]", "app/renovate"}
        or "**Automerge**: Enabled" not in (pr["body"] or "")
        or pr["requested_reviewers"]
        or pr["requested_teams"]
        or pr["mergeable"] is not True
        or pr["mergeable_state"] != "clean"
    ):
        return None
    base = pr["base"]["sha"]
    head = pr["head"]["sha"]
    comparison = api(f"repos/{repo}/compare/{base}...{head}")
    if comparison["behind_by"]:
        return None
    green_at = green_since(repo, head)
    return green_at if green_at and now - green_at >= MAX_WAIT else None


def run(repo: str, now: datetime) -> None:
    issues = {
        int(issue["title"].removeprefix(ALERT_PREFIX)): issue
        for issue in pages(f"repos/{repo}/issues?state=all")
        if issue["title"].startswith(ALERT_PREFIX)
        and issue["title"].removeprefix(ALERT_PREFIX).isdigit()
        and "pull_request" not in issue
    }
    open_prs = list(pages(f"repos/{repo}/pulls?state=open"))
    open_numbers = {pr["number"] for pr in open_prs}
    for summary in open_prs:
        pr = api(f"repos/{repo}/pulls/{summary['number']}")
        green_at = stale_pr(repo, pr, now)
        if green_at is None:
            continue
        number = pr["number"]
        if number in issues:
            if issues[number]["state"] == "closed":
                api(
                    f"repos/{repo}/issues/{issues[number]['number']}",
                    method="PATCH",
                    fields={"state": "open"},
                )
                print(f"Reopened stale Renovate alert for PR #{number}")
            continue
        body = (
            f"Renovate PR #{number} has been green and up to date since "
            f"{green_at:%Y-%m-%d %H:%M UTC}, over six hours ago.\n\n"
            f"PR: {pr['html_url']}\n"
            f"Mend job history: https://developer.mend.io/github/{repo}\n\n"
            "Check the latest Mend job status and log for the merge decision. "
            "The Dependency Dashboard has a supported manual-job checkbox "
            "if a retry is needed. This alert does not merge the PR.\n"
        )
        api(
            f"repos/{repo}/issues",
            method="POST",
            fields={"title": f"{ALERT_PREFIX}{number}", "body": body},
        )
        print(f"Opened stale Renovate alert for PR #{number}")
    for number, issue in issues.items():
        if number not in open_numbers and issue["state"] == "open":
            api(
                f"repos/{repo}/issues/{issue['number']}",
                method="PATCH",
                fields={"state": "closed"},
            )
            print(f"Closed resolved Renovate alert for PR #{number}")


if __name__ == "__main__":
    run(os.environ["GITHUB_REPOSITORY"], datetime.now(timezone.utc))
