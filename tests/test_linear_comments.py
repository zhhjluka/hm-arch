import pytest


def test_fetch_issue_comments_uses_linear_graphql_api() -> None:
    from hm_arch import LinearClient, LinearIssueComment

    calls = []

    def transport(url, payload, headers):
        calls.append((url, payload, headers))
        return {
            "data": {
                "issue": {
                    "comments": {
                        "nodes": [
                            {
                                "id": "comment-1",
                                "body": "First comment",
                                "createdAt": "2026-06-01T15:00:00.000Z",
                                "user": {"id": "user-1", "name": "Ada"},
                            }
                        ]
                    }
                }
            }
        }

    client = LinearClient(api_key="lin_api_key", transport=transport)

    comments = client.fetch_issue_comments("MEM-6")

    assert comments == [
        LinearIssueComment(
            id="comment-1",
            body="First comment",
            created_at="2026-06-01T15:00:00.000Z",
            user_id="user-1",
            user_name="Ada",
        )
    ]
    url, payload, headers = calls[0]
    assert url == "https://api.linear.app/graphql"
    assert payload["variables"] == {"issueId": "MEM-6", "after": None}
    assert "comments(first: 50, after: $after)" in payload["query"]
    assert headers == {
        "Authorization": "lin_api_key",
        "Content-Type": "application/json",
    }


def test_fetch_issue_comments_reads_api_key_from_environment(monkeypatch) -> None:
    from hm_arch import fetch_linear_issue_comments

    monkeypatch.setenv("LINEAR_API_KEY", "env-token")

    def transport(_url, _payload, headers):
        assert headers["Authorization"] == "env-token"
        return {"data": {"issue": {"comments": {"nodes": []}}}}

    assert fetch_linear_issue_comments("MEM-6", transport=transport) == []


def test_fetch_issue_comments_follows_comment_pages() -> None:
    from hm_arch import LinearClient

    cursors = []

    def transport(_url, payload, _headers):
        cursors.append(payload["variables"]["after"])
        if payload["variables"]["after"] is None:
            return {
                "data": {
                    "issue": {
                        "comments": {
                            "nodes": [
                                {
                                    "id": "comment-1",
                                    "body": "First page",
                                    "createdAt": "2026-06-01T15:00:00.000Z",
                                    "user": None,
                                }
                            ],
                            "pageInfo": {
                                "hasNextPage": True,
                                "endCursor": "cursor-1",
                            },
                        }
                    }
                }
            }
        return {
            "data": {
                "issue": {
                    "comments": {
                        "nodes": [
                            {
                                "id": "comment-2",
                                "body": "Second page",
                                "createdAt": "2026-06-01T15:01:00.000Z",
                                "user": None,
                            }
                        ],
                        "pageInfo": {
                            "hasNextPage": False,
                            "endCursor": None,
                        },
                    }
                }
            }
        }

    comments = LinearClient(api_key="lin_api_key", transport=transport).fetch_issue_comments(
        "MEM-6"
    )

    assert [comment.body for comment in comments] == ["First page", "Second page"]
    assert cursors == [None, "cursor-1"]


def test_default_transport_uses_configured_timeout(monkeypatch) -> None:
    import hm_arch.linear as linear_module

    timeouts = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"data": {"issue": {"comments": {"nodes": []}}}}'

    def fake_urlopen(_request, timeout):
        timeouts.append(timeout)
        return Response()

    monkeypatch.setattr(linear_module.request, "urlopen", fake_urlopen)

    client = linear_module.LinearClient(api_key="lin_api_key", timeout=2.5)

    assert client.fetch_issue_comments("MEM-6") == []
    assert timeouts == [2.5]


def test_fetch_issue_comments_requires_api_key(monkeypatch) -> None:
    from hm_arch import fetch_linear_issue_comments

    monkeypatch.delenv("LINEAR_API_KEY", raising=False)

    with pytest.raises(ValueError, match="LINEAR_API_KEY"):
        fetch_linear_issue_comments("MEM-6", transport=lambda *_args: {})
