#!/usr/bin/env python3
"""
Script to notify contributors when their code goes live in a release.

This script:
1. Identifies all contributors between two release tags
2. Gathers their commit information
3. Can send email notifications via Resend, SMTP, or other providers
4. Supports dry-run mode to preview notifications

Usage:
    # Preview contributors for a release
    python scripts/notify_release_contributors.py --from-tag 1.2.1 --to-tag 1.3.0 --dry-run

    # Send email notifications via Resend (recommended)
    python scripts/notify_release_contributors.py --from-tag 1.2.1 --to-tag 1.3.0 \
        --email-provider resend

    # Send via SMTP
    python scripts/notify_release_contributors.py --from-tag 1.2.1 --to-tag 1.3.0 \
        --email-provider smtp --smtp-host smtp.gmail.com --smtp-port 587 \
        --smtp-user user@gmail.com --smtp-password $SMTP_PASSWORD

Environment Variables:
    GITHUB_TOKEN: Required for fetching contributor info from GitHub API
    RESEND_API_KEY: Required when using Resend provider
    SMTP_PASSWORD: Can be used instead of --smtp-password flag
"""

import argparse
import json
import os
import re
import smtplib
import subprocess
import sys
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any


@dataclass
class Contributor:
    """Represents a contributor to the release."""

    username: str
    email: str
    name: str
    commit_count: int
    commits: list[dict[str, str]]

    @property
    def is_bot(self) -> bool:
        return "[bot]" in self.username or self.username.endswith("-bot")

    @property
    def has_valid_email(self) -> bool:
        """Check if email is valid (not a GitHub noreply address)."""
        if not self.email:
            return False
        # GitHub noreply emails are not useful for direct contact
        # but we can still try to resolve actual emails via GitHub API
        return "@users.noreply.github.com" not in self.email


def run_command(cmd: list[str], capture_output: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command and return the result."""
    return subprocess.run(cmd, capture_output=capture_output, text=True, check=True)


def get_github_token() -> str | None:
    """Get GitHub token from environment."""
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def github_api_request(endpoint: str) -> dict[str, Any]:
    """Make a GitHub API request using gh CLI."""
    token = get_github_token()
    if not token:
        raise ValueError("GITHUB_TOKEN environment variable is required")

    env = os.environ.copy()
    env["GH_TOKEN"] = token

    result = subprocess.run(
        ["gh", "api", endpoint, "-H", "Accept: application/vnd.github+json"],
        capture_output=True,
        text=True,
        env=env,
    )

    if result.returncode != 0:
        raise RuntimeError(f"GitHub API request failed: {result.stderr}")

    return json.loads(result.stdout)


def get_contributors_between_tags(
    repo: str, from_tag: str, to_tag: str
) -> list[Contributor]:
    """
    Get all contributors between two git tags using GitHub API.

    Args:
        repo: Repository in 'owner/repo' format
        from_tag: Starting tag (exclusive)
        to_tag: Ending tag (inclusive)

    Returns:
        List of Contributor objects
    """
    # Use GitHub compare API to get commits between tags
    endpoint = f"repos/{repo}/compare/{from_tag}...{to_tag}"

    try:
        data = github_api_request(endpoint)
    except RuntimeError as e:
        print(f"Warning: GitHub API request failed: {e}")
        print("Falling back to git log...")
        return get_contributors_via_git(from_tag, to_tag)

    # Group commits by author
    contributors_map: dict[str, Contributor] = {}

    for commit_data in data.get("commits", []):
        author = commit_data.get("author") or {}
        commit_info = commit_data.get("commit", {})
        author_info = commit_info.get("author", {})

        username = author.get("login", "unknown")
        email = author_info.get("email", "")
        name = author_info.get("name", username)
        sha = commit_data.get("sha", "")[:7]
        message = commit_info.get("message", "").split("\n")[0]  # First line only

        if username not in contributors_map:
            contributors_map[username] = Contributor(
                username=username,
                email=email,
                name=name,
                commit_count=0,
                commits=[],
            )

        contributors_map[username].commit_count += 1
        contributors_map[username].commits.append({"sha": sha, "message": message})

    return list(contributors_map.values())


def get_contributors_via_git(from_tag: str, to_tag: str) -> list[Contributor]:
    """Fallback method using git log directly."""
    result = run_command(
        [
            "git",
            "--no-pager",
            "log",
            f"{from_tag}..{to_tag}",
            "--format=%H|%ae|%an|%s",
            "--no-merges",
        ]
    )

    contributors_map: dict[str, Contributor] = {}

    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("|", 3)
        if len(parts) < 4:
            continue

        sha, email, name, message = parts
        username = email.split("@")[0]

        # Extract username from GitHub noreply email
        noreply_match = re.match(r"(\d+\+)?([^@]+)@users\.noreply\.github\.com", email)
        if noreply_match:
            username = noreply_match.group(2)

        if username not in contributors_map:
            contributors_map[username] = Contributor(
                username=username,
                email=email,
                name=name,
                commit_count=0,
                commits=[],
            )

        contributors_map[username].commit_count += 1
        contributors_map[username].commits.append({"sha": sha[:7], "message": message})

    return list(contributors_map.values())


def resolve_user_email(username: str) -> str | None:
    """Try to resolve a user's public email from their GitHub profile."""
    try:
        user_data = github_api_request(f"users/{username}")
        return user_data.get("email")
    except Exception:
        return None


def generate_email_content(
    contributor: Contributor, release_tag: str, repo: str, release_url: str
) -> tuple[str, str, str]:
    """
    Generate email subject and body (plain text and HTML).

    Returns:
        Tuple of (subject, plain_text_body, html_body)
    """
    subject = f"🎉 Your code is live in {repo.split('/')[-1]} {release_tag}!"

    # List of commits (limit to 10 for readability)
    commits_display = contributor.commits[:10]
    commits_text = "\n".join(
        f"  • {c['sha']}: {c['message'][:60]}..." if len(c["message"]) > 60 else f"  • {c['sha']}: {c['message']}"
        for c in commits_display
    )
    if len(contributor.commits) > 10:
        commits_text += f"\n  ... and {len(contributor.commits) - 10} more commits"

    plain_text = f"""Hi {contributor.name},

Great news! Your contributions have been included in {repo.split('/')[-1]} {release_tag}, which is now live in production! 🚀

Your contributions ({contributor.commit_count} commit{'s' if contributor.commit_count > 1 else ''}):
{commits_text}

View the full release notes: {release_url}

Please take a moment to verify that your changes are working as intended in production. If you notice any issues or unexpected behavior, we'd appreciate it if you could submit follow-up fixes as needed.

Thank you for your valuable contributions to the project!

Best regards,
The OpenHands Team
"""

    commits_html = "".join(
        f"<li><code>{c['sha']}</code>: {c['message'][:60]}{'...' if len(c['message']) > 60 else ''}</li>"
        for c in commits_display
    )
    if len(contributor.commits) > 10:
        commits_html += f"<li><em>... and {len(contributor.commits) - 10} more commits</em></li>"

    html_body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 10px 10px 0 0; }}
        .content {{ background: #f9fafb; padding: 30px; border-radius: 0 0 10px 10px; }}
        .commits {{ background: white; padding: 15px; border-radius: 8px; margin: 20px 0; }}
        .commits ul {{ margin: 0; padding-left: 20px; }}
        .commits li {{ margin: 8px 0; }}
        .cta {{ display: inline-block; background: #667eea; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; margin-top: 20px; }}
        .notice {{ background: #fef3c7; border-left: 4px solid #f59e0b; padding: 12px 16px; margin: 20px 0; border-radius: 0 8px 8px 0; }}
        code {{ background: #e5e7eb; padding: 2px 6px; border-radius: 4px; font-size: 0.9em; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 style="margin: 0;">🎉 Your Code is Live!</h1>
            <p style="margin: 10px 0 0 0; opacity: 0.9;">{repo.split('/')[-1]} {release_tag}</p>
        </div>
        <div class="content">
            <p>Hi {contributor.name},</p>
            <p>Great news! Your contributions have been included in <strong>{repo.split('/')[-1]} {release_tag}</strong>, which is now live in production! 🚀</p>

            <div class="commits">
                <strong>Your contributions ({contributor.commit_count} commit{'s' if contributor.commit_count > 1 else ''}):</strong>
                <ul>{commits_html}</ul>
            </div>

            <div class="notice">
                <strong>🔍 Please verify your changes</strong><br>
                Take a moment to check that your changes are working as intended in production. If you notice any issues or unexpected behavior, please submit follow-up fixes as needed.
            </div>

            <p>Thank you for your valuable contributions to the project!</p>

            <a href="{release_url}" class="cta">View Release Notes →</a>

            <p style="margin-top: 30px; color: #6b7280; font-size: 0.9em;">
                Best regards,<br>
                The OpenHands Team
            </p>
        </div>
    </div>
</body>
</html>
"""

    return subject, plain_text, html_body


def send_email_smtp(
    to_email: str,
    subject: str,
    plain_text: str,
    html_body: str,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    from_email: str,
) -> bool:
    """Send email via SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email

    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(from_email, [to_email], msg.as_string())
        return True
    except Exception as e:
        print(f"  Error sending email to {to_email}: {e}")
        return False


def send_email_resend(
    to_email: str,
    subject: str,
    plain_text: str,
    html_body: str,
    api_key: str,
    from_email: str,
) -> bool:
    """Send email via Resend API."""
    try:
        import resend
    except ImportError:
        print("Error: 'resend' package required. Install with: pip install resend")
        return False

    resend.api_key = api_key

    try:
        resend.Emails.send({
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "html": html_body,
            "text": plain_text,
        })
        return True
    except Exception as e:
        print(f"  Error sending email to {to_email}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Notify contributors when their code goes live in a release"
    )
    parser.add_argument(
        "--repo",
        default="OpenHands/OpenHands",
        help="GitHub repository (owner/repo format)",
    )
    parser.add_argument("--from-tag", required=True, help="Starting tag (exclusive)")
    parser.add_argument("--to-tag", required=True, help="Ending tag (inclusive)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview notifications without sending emails",
    )
    parser.add_argument(
        "--include-bots",
        action="store_true",
        help="Include bot accounts in notifications",
    )
    parser.add_argument(
        "--resolve-emails",
        action="store_true",
        help="Try to resolve emails from GitHub profiles for noreply addresses",
    )
    parser.add_argument(
        "--output-json",
        type=str,
        help="Output contributor data to JSON file",
    )

    # Email configuration
    parser.add_argument(
        "--email-provider",
        choices=["smtp", "resend", "none"],
        default="none",
        help="Email provider to use",
    )
    parser.add_argument(
        "--from-email",
        default="OpenHands Team <contact@all-hands.dev>",
        help="Sender email address",
    )

    # SMTP settings
    parser.add_argument("--smtp-host", help="SMTP server hostname")
    parser.add_argument("--smtp-port", type=int, default=587, help="SMTP server port")
    parser.add_argument("--smtp-user", help="SMTP username")
    parser.add_argument("--smtp-password", help="SMTP password (or use SMTP_PASSWORD env)")

    # Resend settings
    parser.add_argument(
        "--resend-api-key",
        help="Resend API key (or use RESEND_API_KEY env)",
    )

    args = parser.parse_args()

    print(f"🔍 Finding contributors between {args.from_tag} and {args.to_tag}...")

    # Get contributors
    contributors = get_contributors_between_tags(args.repo, args.from_tag, args.to_tag)

    # Filter bots if needed
    if not args.include_bots:
        bots = [c for c in contributors if c.is_bot]
        contributors = [c for c in contributors if not c.is_bot]
        if bots:
            print(f"   Excluding {len(bots)} bot account(s): {', '.join(b.username for b in bots)}")

    # Sort by commit count
    contributors.sort(key=lambda c: c.commit_count, reverse=True)

    print(f"\n📊 Found {len(contributors)} contributor(s):\n")
    for c in contributors:
        email_status = "✓" if c.has_valid_email else "⚠ noreply"
        print(f"   {c.name} (@{c.username})")
        print(f"      Email: {c.email} [{email_status}]")
        print(f"      Commits: {c.commit_count}")
        print()

    # Try to resolve emails for noreply addresses
    if args.resolve_emails:
        print("🔎 Resolving emails from GitHub profiles...")
        for c in contributors:
            if not c.has_valid_email:
                resolved = resolve_user_email(c.username)
                if resolved:
                    print(f"   ✓ Resolved {c.username}: {resolved}")
                    c.email = resolved
                else:
                    print(f"   ✗ Could not resolve email for {c.username}")

    # Output JSON if requested
    if args.output_json:
        output_data = {
            "release": args.to_tag,
            "previous_release": args.from_tag,
            "repository": args.repo,
            "contributors": [
                {
                    "username": c.username,
                    "email": c.email,
                    "name": c.name,
                    "commit_count": c.commit_count,
                    "has_valid_email": c.has_valid_email,
                    "commits": c.commits,
                }
                for c in contributors
            ],
        }
        with open(args.output_json, "w") as f:
            json.dump(output_data, f, indent=2)
        print(f"\n📁 Contributor data saved to {args.output_json}")

    # Generate release URL
    release_url = f"https://github.com/{args.repo}/releases/tag/{args.to_tag}"

    # Send emails if not dry run
    if args.dry_run:
        print("\n📧 DRY RUN - Email preview:\n")
        for c in contributors:
            if c.has_valid_email:
                subject, plain_text, _ = generate_email_content(
                    c, args.to_tag, args.repo, release_url
                )
                print(f"To: {c.email}")
                print(f"Subject: {subject}")
                print("-" * 40)
                print(plain_text[:500] + "..." if len(plain_text) > 500 else plain_text)
                print("=" * 60 + "\n")
    elif args.email_provider != "none":
        print(f"\n📧 Sending notifications via {args.email_provider}...")

        # Filter to only those with valid emails
        notifiable = [c for c in contributors if c.has_valid_email]
        if len(notifiable) < len(contributors):
            print(
                f"   ⚠ Skipping {len(contributors) - len(notifiable)} contributor(s) with noreply emails"
            )

        sent_count = 0
        failed_count = 0

        for c in notifiable:
            subject, plain_text, html_body = generate_email_content(
                c, args.to_tag, args.repo, release_url
            )

            success = False
            if args.email_provider == "smtp":
                password = args.smtp_password or os.environ.get("SMTP_PASSWORD")
                if not all([args.smtp_host, args.smtp_user, password]):
                    print("Error: SMTP requires --smtp-host, --smtp-user, and --smtp-password")
                    sys.exit(1)
                success = send_email_smtp(
                    c.email,
                    subject,
                    plain_text,
                    html_body,
                    args.smtp_host,
                    args.smtp_port,
                    args.smtp_user,
                    password,
                    args.from_email,
                )
            elif args.email_provider == "resend":
                api_key = args.resend_api_key or os.environ.get("RESEND_API_KEY")
                if not api_key:
                    print("Error: Resend requires --resend-api-key or RESEND_API_KEY env")
                    sys.exit(1)
                success = send_email_resend(
                    c.email, subject, plain_text, html_body, api_key, args.from_email
                )

            if success:
                print(f"   ✓ Sent to {c.name} <{c.email}>")
                sent_count += 1
            else:
                print(f"   ✗ Failed to send to {c.name} <{c.email}>")
                failed_count += 1

        print(f"\n📊 Summary: {sent_count} sent, {failed_count} failed")
    else:
        print("\n💡 To send emails, use --email-provider (smtp or sendgrid)")
        print("   Or use --dry-run to preview email content")


if __name__ == "__main__":
    main()
