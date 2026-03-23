"""Pytest configuration for server.routes tests.

This module sets up the test environment for server routes.

Note: The server.routes.integration.github module uses lazy initialization
for external dependencies (TokenManager, GithubManager, etc.), so it can be
imported directly without requiring environment variables to be set.
"""
