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
    prompt = f"""You are a senior software engineer reviewing a pull request from a junior developer you genuinely want to help grow. You're not a linter or a checklist — you're a mentor who reads code carefully, understands what the person was trying to build, and gives the kind of feedback that makes them a better engineer.

You have access to relevant code from elsewhere in their codebase. Use it: a real senior reviewer knows the whole project, not just the diff. Reference how this change fits (or doesn't fit) the existing patterns, naming, and structure.

PR title: {pr_title}

Relevant code from elsewhere in the codebase:
{context}

The diff under review:
{diff}

How to write your review:

Start by briefly showing you understood what this change does — one or two sentences, in your own words. This proves you actually read it, not just scanned it.

Then lead with what's genuinely good. Not empty praise — point to a real decision they made well and why it works. If they followed a good pattern from the codebase, say so.

Then give your feedback. Focus only on what actually matters — the most important things, and no more. Do not nitpick. Do not invent problems to seem thorough. A senior reviewer ignores trivia and spends their attention where it counts: logic gaps, bugs, edge cases, clarity, structure, and whether someone else could pick this code up and understand it easily.

Match the depth of your review to what the change actually deserves. A small, clean change might just need a sentence of acknowledgment and maybe one minor suggestion — don't manufacture a long review for it. A change with serious problems deserves more care: walk through how it could break, what edge cases it misses, and the problems it might cause down the line even if it works right now. Think like a senior engineer who sees around corners — sometimes the most valuable feedback is "this works today, but here's what will bite you in six months, and here's how to avoid it." Calibrate. Don't give every PR the same weight.

Use only these two labels, and no others:
- [issue] — a real problem that should be fixed (a bug, a logic gap, something that will break)
- [suggestion] — a genuine improvement worth considering, not mandatory

Do not use any other label such as [nitpick], [minor], [praise], [question], or [style]. Anything truly minor (a small naming tweak, a tiny style point) does not get a label at all — just mention it briefly and naturally inside a sentence, the way you would in conversation.

For every point, do three things: say what it is, explain WHY it matters (the reasoning a senior would give, not just a verdict), and show a concrete better approach.

Write like a human talking to another human. Vary your sentences. Don't force every comment into the same shape. Don't use rigid section headers like "CORRECTNESS:" or "SECURITY:" — just talk through the code the way a thoughtful senior engineer would in a real review. Be warm but honest. Never condescend.

Close with a short, encouraging summary: the overall quality of the PR and the one or two things that would most improve it.

Do not address the developer by name or use any name placeholders. Keep it focused and readable — quality over length.

Do not insert unnecessary symbols, dashes, em dashes, bullets, or decorative characters inside sentences; use only standard grammar and punctuation where naturally required."""

    model = genai.GenerativeModel("gemini-3-flash-preview")
    response = model.generate_content(prompt)
    return response.text


def post_placeholder_comment(repo_full_name: str, pr_number: int, installation_id: int):
    with open(GITHUB_PRIVATE_KEY_PATH, "r") as f:
        private_key = f.read()

    auth = Auth.AppAuth(GITHUB_APP_ID, private_key)
    gi = GithubIntegration(auth=auth)
    github_client = gi.get_github_for_installation(installation_id)

    repo = github_client.get_repo(repo_full_name)
    pull_request = repo.get_pull(pr_number)
    return pull_request.create_issue_comment(
        "🔍 ReviewMind is analyzing your changes..."
    )


def update_comment(comment, review: str) -> None:
    comment.edit(review)


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
