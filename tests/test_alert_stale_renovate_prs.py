"""Tests for the stale Renovate PR alert's eligibility gates."""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import alert_stale_renovate_prs as monitor  # noqa: E402


NOW = datetime(2026, 9, 25, 14, 0, tzinfo=timezone.utc)
GREEN_AT = "2026-09-25T07:00:00Z"
REPO = "SpencerRWood/infrastructure"


def pr():
    return {
        "number": 40,
        "draft": False,
        "user": {"login": "renovate[bot]"},
        "body": "🚦 **Automerge**: Enabled.",
        "requested_reviewers": [],
        "requested_teams": [],
        "mergeable": True,
        "mergeable_state": "clean",
        "base": {"sha": "base"},
        "head": {"sha": "head"},
        "html_url": "https://github.com/SpencerRWood/infrastructure/pull/40",
    }


def github(path, **_kwargs):
    if "/compare/" in path:
        return {"behind_by": 0}
    if "/check-runs" in path:
        return {
            "check_runs": [{
                "name": monitor.REQUIRED_CHECK,
                "status": "completed",
                "conclusion": "success",
                "completed_at": GREEN_AT,
            }]
        }
    if "/status" in path:
        return {
            "statuses": [{
                "context": monitor.REQUIRED_STATUS,
                "state": "success",
                "updated_at": GREEN_AT,
            }]
        }
    raise AssertionError(path)


class StaleRenovateTests(unittest.TestCase):
    @patch.object(monitor, "api", side_effect=github)
    def test_green_eligible_digest_pr_is_stale(self, _api):
        self.assertEqual(monitor.stale_pr(REPO, pr(), NOW), monitor.timestamp(GREEN_AT))

    @patch.object(monitor, "api", side_effect=github)
    def test_manual_update_is_not_alerted(self, _api):
        candidate = pr()
        candidate["body"] = "🚦 **Automerge**: Disabled."
        self.assertIsNone(monitor.stale_pr(REPO, candidate, NOW))

    @patch.object(monitor, "api", side_effect=github)
    def test_recent_green_pr_is_not_alerted(self, _api):
        self.assertIsNone(
            monitor.stale_pr(REPO, pr(), datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
        )

    @patch.object(monitor, "api")
    def test_behind_branch_is_not_alerted(self, mock_api):
        mock_api.return_value = {"behind_by": 1}
        self.assertIsNone(monitor.stale_pr(REPO, pr(), NOW))

    @patch.object(monitor, "api")
    def test_failed_check_is_not_alerted(self, mock_api):
        def failing_github(path, **kwargs):
            result = github(path, **kwargs)
            if "/check-runs" in path:
                result["check_runs"][0]["conclusion"] = "failure"
            return result

        mock_api.side_effect = failing_github
        self.assertIsNone(monitor.stale_pr(REPO, pr(), NOW))

    @patch.object(monitor, "api")
    @patch.object(monitor, "stale_pr", return_value=monitor.timestamp(GREEN_AT))
    @patch.object(monitor, "pages")
    def test_alert_is_opened_once(self, mock_pages, _stale_pr, mock_api):
        mock_pages.side_effect = [[], [{"number": 40}], [
            {"number": 51, "title": f"{monitor.ALERT_PREFIX}40", "state": "open"}
        ], [{"number": 40}]]
        mock_api.return_value = pr()
        monitor.run(REPO, NOW)
        monitor.run(REPO, NOW)
        creations = [
            call for call in mock_api.call_args_list if call.kwargs.get("method") == "POST"
        ]
        self.assertEqual(len(creations), 1)
        self.assertEqual(creations[0].kwargs["fields"]["title"], f"{monitor.ALERT_PREFIX}40")

    @patch.object(monitor, "api")
    @patch.object(monitor, "pages")
    def test_alert_closes_after_pr_closes(self, mock_pages, mock_api):
        mock_pages.side_effect = [[
            {"number": 51, "title": f"{monitor.ALERT_PREFIX}40", "state": "open"}
        ], []]
        monitor.run(REPO, NOW)
        mock_api.assert_called_once_with(
            f"repos/{REPO}/issues/51", method="PATCH", fields={"state": "closed"}
        )


if __name__ == "__main__":
    unittest.main()
