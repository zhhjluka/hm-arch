"""Helpers for reading Linear issue comments."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib import request


LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"

GraphQLTransport = Callable[
    [str, Mapping[str, Any], Mapping[str, str]], Mapping[str, Any]
]

_ISSUE_COMMENTS_QUERY = """
query IssueComments($issueId: String!, $after: String) {
  issue(id: $issueId) {
    comments(first: 50, after: $after) {
      nodes {
        id
        body
        createdAt
        user {
          id
          name
        }
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""


@dataclass(frozen=True)
class LinearIssueComment:
    """A comment fetched from a Linear issue."""

    id: str
    body: str
    created_at: str
    user_id: str | None = None
    user_name: str | None = None


class LinearClient:
    """Small Linear GraphQL client for issue comments."""

    def __init__(
        self,
        *,
        api_key: str,
        api_url: str = LINEAR_GRAPHQL_URL,
        transport: GraphQLTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        if not api_key:
            raise ValueError("Linear API key is required.")

        self._api_key = api_key
        self._api_url = api_url
        self._transport = transport or (
            lambda url, payload, headers: _urlopen_transport(
                url, payload, headers, timeout=timeout
            )
        )

    @classmethod
    def from_env(
        cls,
        *,
        env_var: str = "LINEAR_API_KEY",
        api_url: str = LINEAR_GRAPHQL_URL,
        transport: GraphQLTransport | None = None,
        timeout: float = 10.0,
    ) -> "LinearClient":
        api_key = os.environ.get(env_var)
        if not api_key:
            raise ValueError(f"{env_var} is required to fetch Linear issue comments.")
        return cls(api_key=api_key, api_url=api_url, transport=transport, timeout=timeout)

    def fetch_issue_comments(self, issue_id: str) -> list[LinearIssueComment]:
        """Fetch all comments for a Linear issue ID or UUID."""

        comments: list[LinearIssueComment] = []
        after: str | None = None
        while True:
            response = self._transport(
                self._api_url,
                {
                    "query": _ISSUE_COMMENTS_QUERY,
                    "variables": {"issueId": issue_id, "after": after},
                },
                {
                    "Authorization": self._api_key,
                    "Content-Type": "application/json",
                },
            )
            comments.extend(_parse_issue_comments(response))

            page_info = _parse_comment_page_info(response)
            if not page_info.get("hasNextPage"):
                return comments

            after = page_info.get("endCursor")
            if after is None:
                raise RuntimeError("Linear response is missing the next comments cursor.")


def fetch_linear_issue_comments(
    issue_id: str,
    *,
    api_key: str | None = None,
    transport: GraphQLTransport | None = None,
    timeout: float = 10.0,
) -> list[LinearIssueComment]:
    """Fetch Linear issue comments, reading LINEAR_API_KEY when no key is passed."""

    client = (
        LinearClient(api_key=api_key, transport=transport, timeout=timeout)
        if api_key is not None
        else LinearClient.from_env(transport=transport, timeout=timeout)
    )
    return client.fetch_issue_comments(issue_id)


def _parse_issue_comments(response: Mapping[str, Any]) -> list[LinearIssueComment]:
    errors = response.get("errors")
    if errors:
        raise RuntimeError(f"Linear GraphQL request failed: {errors}")

    issue = response.get("data", {}).get("issue")
    if issue is None:
        return []

    nodes = issue.get("comments", {}).get("nodes", [])
    comments: list[LinearIssueComment] = []
    for node in nodes:
        user = node.get("user") or {}
        comments.append(
            LinearIssueComment(
                id=node["id"],
                body=node["body"],
                created_at=node["createdAt"],
                user_id=user.get("id"),
                user_name=user.get("name"),
            )
        )
    return comments


def _parse_comment_page_info(response: Mapping[str, Any]) -> Mapping[str, Any]:
    issue = response.get("data", {}).get("issue")
    if issue is None:
        return {"hasNextPage": False}
    return issue.get("comments", {}).get("pageInfo", {"hasNextPage": False})


def _urlopen_transport(
    url: str,
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
    *,
    timeout: float,
) -> Mapping[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    http_request = request.Request(url, data=data, headers=dict(headers), method="POST")
    with request.urlopen(http_request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))
