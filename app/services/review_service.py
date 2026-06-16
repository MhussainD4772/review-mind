import logging
import os

import google.generativeai as genai
from dotenv import load_dotenv
from github import Auth, GithubIntegration

load_dotenv()

logger = logging.getLogger(__name__)

GITHUB_APP_ID = os.getenv("GITHUB_APP_ID", "0")
GITHUB_PRIVATE_KEY_PATH = os.getenv("GITHUB_PRIVATE_KEY_PATH", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

genai.configure(api_key=GEMINI_API_KEY)


def fetch_pr_diff(repo_full_name: str, pr_number: int, installation_id: int) -> str:
    with open(GITHUB_PRIVATE_KEY_PATH, "r") as f:
        private_key = f.read()

    auth = Auth.AppAuth(GITHUB_APP_ID, private_key)
    gi = GithubIntegration(auth=auth)
    github_client = gi.get_github_for_installation(installation_id)

    repo = github_client.get_repo(repo_full_name)
    pull_request = repo.get_pull(pr_number)

    files = pull_request.get_files()
    diff_text = ""
    for file in files:
        diff_text += f"\n--- {file.filename} ---\n"
        if file.patch:
            diff_text += file.patch

    return diff_text


def generate_review(diff: str, pr_title: str, context: str = "") -> str:
    prompt = f"""You are a senior software engineer conducting a pull request review.
Your job is to mentor a junior developer — not just identify problems,
but explain WHY each issue matters and HOW to think about it better.

PR Title: {pr_title}

Relevant code from elsewhere in the codebase (for context):
{context}

Code diff:
{diff}

Review the changes across these dimensions:
1. CORRECTNESS — does the code do what it intends? Any bugs or logic errors?
2. EDGE CASES — what inputs or states could break this?
3. CODE CLARITY — is it readable and self-explanatory?
4. STRUCTURE — is the code organized well? Are responsibilities clear?
5. SECURITY — any vulnerabilities, exposed data, or unsafe patterns?
6. PERFORMANCE — any obvious inefficiencies worth flagging?
7. ERROR HANDLING — are failures handled gracefully?

For each issue you find:
- State clearly what the problem is
- Explain WHY it matters
- Show a concrete better approach

Do not address the developer by name or use any name placeholders.
Be specific and constructive. If a section looks good, say so briefly.
End with a short overall summary of the PR quality and the top 1-2 things to improve.
Keep the review concise — maximum 600 words. Focus on the most impactful issues only."""

    model = genai.GenerativeModel("gemini-2.5-flash")
    response = model.generate_content(prompt)
    return response.text


def post_review_comment(
    repo_full_name: str, pr_number: int, review: str, installation_id: int
) -> None:
    with open(GITHUB_PRIVATE_KEY_PATH, "r") as f:
        private_key = f.read()

    auth = Auth.AppAuth(GITHUB_APP_ID, private_key)
    gi = GithubIntegration(auth=auth)
    github_client = gi.get_github_for_installation(installation_id)

    repo = github_client.get_repo(repo_full_name)
    pull_request = repo.get_pull(pr_number)
    pull_request.create_issue_comment(review)


def fetch_pr_changed_files(
    repo_full_name: str, pr_number: int, installation_id: int
) -> list[str]:
    with open(GITHUB_PRIVATE_KEY_PATH, "r") as f:
        private_key = f.read()

    auth = Auth.AppAuth(GITHUB_APP_ID, private_key)
    gi = GithubIntegration(auth=auth)
    github_client = gi.get_github_for_installation(installation_id)

    repo = github_client.get_repo(repo_full_name)
    pull_request = repo.get_pull(pr_number)

    return [f.filename for f in pull_request.get_files()]
