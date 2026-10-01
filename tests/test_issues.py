from scout import issues

ISSUES = [
    {
        "title": "[HDS-0001] 4-star hotel, Bordeaux",
        "labels": [{"name": "Status: Shortlist"}],
        "state": "open",
        "comments": 3,
        "html_url": "https://github.com/me/repo/issues/1",
        "updated_at": "2026-10-01T08:00:00Z",
    },
    {"title": "[HDS-0002] Hotel in Lyon", "labels": [], "state": "closed", "comments": 0, "html_url": "u2", "updated_at": "2026-10-01T09:00:00Z"},
    {"title": "[HDS-0003] Hotel in Nice", "labels": [{"name": "question"}], "state": "open", "comments": 1, "html_url": "u3", "updated_at": "2026-10-01T09:00:00Z"},
    {"title": "[HDS-0004] A pull request", "labels": [], "state": "open", "pull_request": {}, "html_url": "u4"},
    {"title": "No ID here", "labels": [], "state": "open", "html_url": "u5"},
]


def test_team_statuses_from_labels_and_state():
    statuses = issues.team_statuses(ISSUES)
    assert statuses["HDS-0001"] == {"status": "shortlist", "issue_url": "https://github.com/me/repo/issues/1", "comments": 3}
    assert statuses["HDS-0002"]["status"] == "closed"
    assert statuses["HDS-0003"]["status"] == "discussing"
    assert "HDS-0004" not in statuses


def test_fetch_pages_through_issues():
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return ISSUES if len(calls) == 1 else []

    statuses = issues.fetch_team_statuses("me/repo", "token", fetch=fake_fetch)
    assert len(calls) == 1  # first page had fewer than 100 items
    assert calls[0].startswith("https://api.github.com/repos/me/repo/issues?state=all")
    assert "HDS-0001" in statuses
