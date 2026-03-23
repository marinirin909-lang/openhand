"""
Mock GitHub API Service for integration tests.

This module provides a real HTTP server that implements the GitHub API endpoints
used by the enterprise code. It tracks all API calls and state, allowing tests
to verify behavior without complex mocking.

Usage:
    service = MockGitHubService()
    service.start()
    
    # Run test code that uses PyGithub...
    
    # Verify
    service.assert_comment_sent("I'm on it")
    service.assert_reaction_added("eyes")
    
    service.stop()
"""

import json
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


@dataclass
class MockGitHubService:
    """In-process mock GitHub API server that tracks state."""

    host: str = "127.0.0.1"
    port: int = 0  # 0 = auto-assign available port

    # Tracked state
    comments: list = field(default_factory=list)
    reactions: list = field(default_factory=list)
    api_calls: list = field(default_factory=list)

    # Configurable data
    repos: dict = field(default_factory=dict)
    issues: dict = field(default_factory=dict)
    pull_requests: dict = field(default_factory=dict)
    issue_comments: dict = field(default_factory=dict)

    # Internal
    _app: FastAPI | None = None
    _server: uvicorn.Server | None = None
    _thread: threading.Thread | None = None
    _ready: threading.Event = field(default_factory=threading.Event)

    def __post_init__(self):
        if self.port == 0:
            self.port = self._find_free_port()

    def _find_free_port(self) -> int:
        """Find an available port."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return s.getsockname()[1]

    @property
    def base_url(self) -> str:
        """URL to use as GitHub API base."""
        return f"http://{self.host}:{self.port}"

    def configure_repo(
        self,
        full_name: str,
        repo_id: int = 1,
        private: bool = False,
    ) -> "MockGitHubService":
        """Configure a repository."""
        owner, name = full_name.split("/")
        self.repos[full_name] = {
            "id": repo_id,
            "name": name,
            "full_name": full_name,
            "private": private,
            "owner": {"login": owner, "id": 1},
        }
        return self

    def configure_issue(
        self,
        full_name: str,
        number: int,
        title: str = "Test Issue",
        body: str = "Test body",
        user_login: str = "testuser",
    ) -> "MockGitHubService":
        """Configure an issue."""
        key = f"{full_name}/{number}"
        self.issues[key] = {
            "id": number,
            "number": number,
            "title": title,
            "body": body,
            "user": {"login": user_login, "id": 1},
        }
        return self

    def configure_pull_request(
        self,
        full_name: str,
        number: int,
        title: str = "Test PR",
        body: str = "Test body",
        user_login: str = "testuser",
    ) -> "MockGitHubService":
        """Configure a pull request."""
        key = f"{full_name}/{number}"
        self.pull_requests[key] = {
            "id": number,
            "number": number,
            "title": title,
            "body": body,
            "user": {"login": user_login, "id": 1},
        }
        return self

    def configure_comment(
        self,
        full_name: str,
        comment_id: int,
        body: str = "Test comment",
        user_login: str = "testuser",
    ) -> "MockGitHubService":
        """Configure an issue comment."""
        key = f"{full_name}/{comment_id}"
        self.issue_comments[key] = {
            "id": comment_id,
            "body": body,
            "user": {"login": user_login, "id": 1},
        }
        return self

    def start(self) -> "MockGitHubService":
        """Start the mock server in a background thread."""
        self._create_app()

        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level="error",
            access_log=False,
        )
        self._server = uvicorn.Server(config)

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

        # Wait for server to be ready by polling
        import requests

        start_time = time.time()
        while time.time() - start_time < 10:
            try:
                resp = requests.get(f"{self.base_url}/_test/state", timeout=0.5)
                if resp.status_code == 200:
                    self._ready.set()
                    break
            except requests.exceptions.RequestException:
                time.sleep(0.1)

        if not self._ready.is_set():
            raise RuntimeError("Mock GitHub server failed to start")

        return self

    def stop(self):
        """Stop the mock server."""
        if self._server:
            self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=5)

    def reset(self):
        """Reset tracked state (but keep configuration)."""
        self.comments.clear()
        self.reactions.clear()
        self.api_calls.clear()

    def _run(self):
        """Run the server (called in background thread)."""
        if self._server:
            self._server.run()

    def _create_app(self):
        """Create the FastAPI app with GitHub API endpoints."""
        app = FastAPI()
        service = self  # Capture reference for closures

        # Middleware to log all API calls
        @app.middleware("http")
        async def log_requests(request: Request, call_next):
            body = None
            if request.method in ("POST", "PUT", "PATCH"):
                body = await request.body()
                try:
                    body = json.loads(body)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    body = body.decode() if isinstance(body, bytes) else body

            service.api_calls.append(
                {
                    "method": request.method,
                    "path": request.url.path,
                    "body": body,
                }
            )

            response = await call_next(request)
            return response

        # Repository endpoints
        @app.get("/repos/{owner}/{repo}")
        async def get_repo(owner: str, repo: str, request: Request):
            full_name = f"{owner}/{repo}"
            if full_name in service.repos:
                data = service.repos[full_name].copy()
                data["url"] = str(request.url)
                return JSONResponse(data)
            # Return default repo
            return JSONResponse(
                {
                    "id": 1,
                    "name": repo,
                    "full_name": full_name,
                    "url": str(request.url),
                    "owner": {"login": owner, "id": 1},
                }
            )

        # Issue endpoints
        @app.get("/repos/{owner}/{repo}/issues/{issue_number}")
        async def get_issue(
            owner: str, repo: str, issue_number: int, request: Request
        ):
            key = f"{owner}/{repo}/{issue_number}"
            if key in service.issues:
                data = service.issues[key].copy()
                data["url"] = str(request.url)
                return JSONResponse(data)
            return JSONResponse(
                {
                    "id": issue_number,
                    "number": issue_number,
                    "title": "Test Issue",
                    "body": "Test body",
                    "url": str(request.url),
                    "user": {"login": "testuser", "id": 1},
                }
            )

        # Pull request endpoints
        @app.get("/repos/{owner}/{repo}/pulls/{pr_number}")
        async def get_pull(owner: str, repo: str, pr_number: int, request: Request):
            key = f"{owner}/{repo}/{pr_number}"
            if key in service.pull_requests:
                data = service.pull_requests[key].copy()
                data["url"] = str(request.url)
                return JSONResponse(data)
            return JSONResponse(
                {
                    "id": pr_number,
                    "number": pr_number,
                    "title": "Test PR",
                    "body": "Test body",
                    "url": str(request.url),
                    "user": {"login": "testuser", "id": 1},
                }
            )

        # Comment endpoints
        @app.get("/repos/{owner}/{repo}/issues/comments/{comment_id}")
        async def get_issue_comment(
            owner: str, repo: str, comment_id: int, request: Request
        ):
            key = f"{owner}/{repo}/{comment_id}"
            if key in service.issue_comments:
                data = service.issue_comments[key].copy()
                data["url"] = str(request.url)
                return JSONResponse(data)
            return JSONResponse(
                {
                    "id": comment_id,
                    "body": "Test comment",
                    "url": str(request.url),
                    "user": {"login": "testuser", "id": 1},
                }
            )

        @app.get("/repos/{owner}/{repo}/issues/{issue_number}/comments")
        async def list_issue_comments(
            owner: str, repo: str, issue_number: int, request: Request
        ):
            # Return empty list by default
            return JSONResponse([])

        @app.post("/repos/{owner}/{repo}/issues/{issue_number}/comments")
        async def create_issue_comment(
            owner: str, repo: str, issue_number: int, request: Request
        ):
            body = await request.json()
            comment_data = {
                "repo": f"{owner}/{repo}",
                "issue_number": issue_number,
                "body": body.get("body", ""),
            }
            service.comments.append(comment_data)

            return JSONResponse(
                {
                    "id": len(service.comments),
                    "body": body.get("body", ""),
                    "url": str(request.url),
                    "user": {"login": "bot", "id": 1},
                },
                status_code=201,
            )

        # Reaction endpoints
        @app.post("/repos/{owner}/{repo}/issues/comments/{comment_id}/reactions")
        async def create_comment_reaction(
            owner: str, repo: str, comment_id: int, request: Request
        ):
            body = await request.json()
            reaction_data = {
                "repo": f"{owner}/{repo}",
                "comment_id": comment_id,
                "content": body.get("content", ""),
            }
            service.reactions.append(reaction_data)

            return JSONResponse(
                {
                    "id": len(service.reactions),
                    "content": body.get("content", ""),
                    "url": str(request.url),
                },
                status_code=201,
            )

        @app.post("/repos/{owner}/{repo}/issues/{issue_number}/reactions")
        async def create_issue_reaction(
            owner: str, repo: str, issue_number: int, request: Request
        ):
            body = await request.json()
            reaction_data = {
                "repo": f"{owner}/{repo}",
                "issue_number": issue_number,
                "content": body.get("content", ""),
            }
            service.reactions.append(reaction_data)

            return JSONResponse(
                {
                    "id": len(service.reactions),
                    "content": body.get("content", ""),
                    "url": str(request.url),
                },
                status_code=201,
            )

        # PR review comment reply
        @app.post(
            "/repos/{owner}/{repo}/pulls/{pr_number}/comments/{comment_id}/replies"
        )
        async def create_review_comment_reply(
            owner: str, repo: str, pr_number: int, comment_id: int, request: Request
        ):
            body = await request.json()
            comment_data = {
                "repo": f"{owner}/{repo}",
                "pr_number": pr_number,
                "reply_to_comment_id": comment_id,
                "body": body.get("body", ""),
            }
            service.comments.append(comment_data)

            return JSONResponse(
                {
                    "id": len(service.comments),
                    "body": body.get("body", ""),
                    "url": str(request.url),
                    "user": {"login": "bot", "id": 1},
                },
                status_code=201,
            )

        # PR comment (not review comment)
        @app.post("/repos/{owner}/{repo}/issues/{pr_number}/comments")
        async def create_pr_comment(
            owner: str, repo: str, pr_number: int, request: Request
        ):
            # PRs can also receive issue comments
            return await create_issue_comment(owner, repo, pr_number, request)

        # Test endpoint to query state
        @app.get("/_test/state")
        async def get_state():
            return JSONResponse(
                {
                    "comments": service.comments,
                    "reactions": service.reactions,
                    "api_calls": service.api_calls,
                }
            )

        @app.post("/_test/reset")
        async def reset_state():
            service.reset()
            return JSONResponse({"status": "ok"})

        self._app = app

    # Assertion helpers
    def get_comments(self) -> list[dict[str, Any]]:
        """Get all comments that were created."""
        return self.comments.copy()

    def get_reactions(self) -> list[dict[str, Any]]:
        """Get all reactions that were created."""
        return self.reactions.copy()

    def get_api_calls(self) -> list[dict[str, Any]]:
        """Get all API calls that were made."""
        return self.api_calls.copy()

    def assert_comment_sent(self, body_contains: str) -> dict[str, Any]:
        """Assert that a comment containing the given text was sent."""
        for comment in self.comments:
            if body_contains in comment.get("body", ""):
                return comment
        raise AssertionError(
            f"No comment containing '{body_contains}' was sent.\n"
            f"Comments sent: {[c.get('body', '')[:50] for c in self.comments]}"
        )

    def assert_reaction_added(self, content: str) -> dict[str, Any]:
        """Assert that a reaction with the given content was added."""
        for reaction in self.reactions:
            if reaction.get("content") == content:
                return reaction
        raise AssertionError(
            f"No '{content}' reaction was added.\n"
            f"Reactions: {[r.get('content') for r in self.reactions]}"
        )

    def assert_no_comments(self):
        """Assert that no comments were sent."""
        if self.comments:
            raise AssertionError(
                f"Expected no comments, but {len(self.comments)} were sent:\n"
                f"{[c.get('body', '')[:50] for c in self.comments]}"
            )

    def wait_for_comment(self, body_contains: str, timeout: float = 5.0) -> dict:
        """Wait for a comment containing the given text."""
        start = time.time()
        while time.time() - start < timeout:
            for comment in self.comments:
                if body_contains in comment.get("body", ""):
                    return comment
            time.sleep(0.1)
        raise TimeoutError(
            f"Timed out waiting for comment containing '{body_contains}'"
        )

    def wait_for_reaction(self, content: str, timeout: float = 5.0) -> dict:
        """Wait for a reaction with the given content."""
        start = time.time()
        while time.time() - start < timeout:
            for reaction in self.reactions:
                if reaction.get("content") == content:
                    return reaction
            time.sleep(0.1)
        raise TimeoutError(f"Timed out waiting for '{content}' reaction")
