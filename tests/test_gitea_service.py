"""Tests for GiteaService merge style handling."""

from dataclasses import dataclass, field
from typing import Any

from update_flake_inputs.gitea_service import GiteaService


@dataclass
class StubGiteaService(GiteaService):
    """GiteaService with controllable API responses."""

    api_url: str = "https://gitea.example.com"
    token: str = "test-token"  # noqa: S105
    owner: str = "test-owner"
    repo: str = "test-repo"

    # Responses to return from _make_request, keyed by (method, endpoint)
    responses: dict[tuple[str, str], Any] = field(default_factory=dict)
    # Requests that were made, as (method, endpoint, data) tuples
    requests: list[tuple[str, str, dict[str, object] | None]] = field(
        default_factory=list,
    )

    def __post_init__(self) -> None:  # noqa: D105
        self.api_url = self.api_url.rstrip("/")
        self._validate_token()

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: dict[str, object] | None = None,
    ) -> Any:  # noqa: ANN401
        self.requests.append((method, endpoint, data))
        return self.responses.get((method, endpoint), {})


def _make_service(
    *,
    merge_style: str = "default",
    default_merge_style: str = "rebase",
) -> StubGiteaService:
    responses = {
        ("GET", "/user"): {"login": "testuser"},
        ("GET", "/repos/test-owner/test-repo"): {
            "permissions": {"admin": True},
            "default_merge_style": default_merge_style,
        },
    }
    return StubGiteaService(merge_style=merge_style, responses=responses)


class TestMergeStyleInit:
    def test_default_fetches_repo_merge_style(self) -> None:
        """Test that 'default' resolves to the repo's default_merge_style."""
        svc = _make_service(default_merge_style="rebase")
        assert svc.merge_style == "rebase"

    def test_default_fetches_squash_merge_style(self) -> None:
        """Test that 'default' resolves to squash when repo is configured for it."""
        svc = _make_service(default_merge_style="squash")
        assert svc.merge_style == "squash"

    def test_default_falls_back_to_merge(self) -> None:
        """When repo response lacks default_merge_style, fall back to merge."""
        responses: dict[tuple[str, str], Any] = {
            ("GET", "/user"): {"login": "testuser"},
            ("GET", "/repos/test-owner/test-repo"): {
                "permissions": {"admin": True},
            },
        }
        svc = StubGiteaService(responses=responses)
        assert svc.merge_style == "merge"

    def test_explicit_merge_style_not_overridden(self) -> None:
        """Test that an explicit merge_style is not replaced by the repo default."""
        svc = _make_service(merge_style="squash", default_merge_style="rebase")
        assert svc.merge_style == "squash"

    def test_empty_string_not_overridden(self) -> None:
        """Test that empty string merge_style is preserved (omit Do from API)."""
        svc = _make_service(merge_style="", default_merge_style="rebase")
        assert svc.merge_style == ""


class TestMergeStyleInRequest:
    def test_merge_style_sent_as_do(self) -> None:
        """Test that merge_style is sent as the Do field in the merge request."""
        svc = _make_service(merge_style="rebase")
        svc.responses[("POST", "/repos/test-owner/test-repo/pulls/1/merge")] = {}

        svc._merge_pull_request(1)  # noqa: SLF001

        _method, _endpoint, data = svc.requests[-1]
        assert data is not None
        assert data["Do"] == "rebase"

    def test_empty_merge_style_omits_do(self) -> None:
        """Test that empty merge_style omits Do from the merge request."""
        svc = _make_service(merge_style="")
        svc.responses[("POST", "/repos/test-owner/test-repo/pulls/1/merge")] = {}

        svc._merge_pull_request(1)  # noqa: SLF001

        _method, _endpoint, data = svc.requests[-1]
        assert data is not None
        assert "Do" not in data

    def test_default_sends_repo_merge_style(self) -> None:
        """Test that 'default' resolves to repo default and sends it as Do."""
        svc = _make_service(default_merge_style="squash")
        svc.responses[("POST", "/repos/test-owner/test-repo/pulls/1/merge")] = {}

        svc._merge_pull_request(1)  # noqa: SLF001

        _method, _endpoint, data = svc.requests[-1]
        assert data is not None
        assert data["Do"] == "squash"
