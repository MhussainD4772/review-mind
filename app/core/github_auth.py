import base64
import os

from github import Auth, GithubIntegration

GITHUB_APP_ID = os.getenv("GITHUB_APP_ID", "0")


def _load_private_key() -> str:
    """Load the GitHub App private key.

    Prefers GITHUB_PRIVATE_KEY (base64-encoded PEM) for deployed
    environments; falls back to GITHUB_PRIVATE_KEY_PATH (file) for
    local development.
    """
    b64_key = os.getenv("GITHUB_PRIVATE_KEY", "")
    if b64_key:
        return base64.b64decode(b64_key).decode("utf-8")

    key_path = os.getenv("GITHUB_PRIVATE_KEY_PATH", "")
    if key_path:
        with open(key_path, "r") as f:
            return f.read()

    raise RuntimeError(
        "No GitHub private key found. Set GITHUB_PRIVATE_KEY (base64) "
        "or GITHUB_PRIVATE_KEY_PATH (file path)."
    )


def get_github_for_installation(installation_id: int):
    """Return an authenticated PyGithub client for an installation."""
    private_key = _load_private_key()
    auth = Auth.AppAuth(GITHUB_APP_ID, private_key)
    gi = GithubIntegration(auth=auth)
    return gi.get_github_for_installation(installation_id)
