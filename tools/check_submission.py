"""Checks a project before you submit it. Run it from the repo root:  python tools/check_submission.py

Each check prints PASS, FAIL or WARN with a one-line fix. Exit code is 1 if anything FAILED.
Uses only the Python standard library. It cannot judge your project, only catch common mistakes.
"""

import re
import subprocess
import sys
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".cache", "wheelhouse", ".pytest_cache"}
CODE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".ipynb", ".java", ".kt", ".go", ".rb", ".cs"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

# A phrase that only appears in each open-source license.
LICENSES = {
    "MIT": "permission is hereby granted, free of charge",
    "Apache-2.0": "apache license version 2.0",
    "BSD": "redistribution and use in source and binary forms",
    "GPL": "gnu general public license",
    "MPL": "mozilla public license",
    "Unlicense": "this is free and unencumbered software released into the public domain",
}
MODEL_PATTERN = re.compile(r"gemma-4-[a-z0-9-]+", re.IGNORECASE)
KEY_PATTERN = re.compile(r"AIza[0-9A-Za-z_-]{35}")
GEMINI_API_PATTERN = re.compile(r"from google import genai|import google\.genai|from google\.genai|generativelanguage\.googleapis\.com")
LOCAL_ONLY_PATTERN = re.compile(r"ollama|localhost|127\.0\.0\.1|11434", re.IGNORECASE)


def read_text(path):
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def project_files(root):
    """Every file in the project, skipping folders we never want to scan."""
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_file() and not SKIP_DIRS.intersection(relative.parts):
            yield path


def git(root, *args):
    """Run a git command. Returns its output, or None if git or the repo is not there."""
    try:
        done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def check_license(root):
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"):
        if (root / name).exists():
            text = " ".join(read_text(root / name).lower().split())
            for license_name, phrase in LICENSES.items():
                if phrase in text:
                    if "[organizer name]" in text:
                        return "WARN", f"{license_name} license found, but it still says [ORGANIZER NAME]", "Put your own name (or your team name) in the LICENSE file."
                    return "PASS", f"{license_name} license found", ""
            return "FAIL", f"{name} is not a recognised open-source license", "Use the MIT LICENSE file that came with the template."
    return "FAIL", "No LICENSE file", "Add a LICENSE file. The template already has an MIT one."


def check_readme_model(root):
    found = MODEL_PATTERN.findall(read_text(root / "README.md"))
    if found:
        return "PASS", f"README names a Gemma model ({found[0].lower()})", ""
    return "FAIL", "README does not name a Gemma 4 model", "Write the model name (for example gemma-4-26b-a4b-it) in README.md."


def check_gemini_api(root):
    code = ""
    for path in project_files(root):
        relative = path.relative_to(root)
        if path.suffix in CODE_EXTENSIONS and relative.parts[0] not in ("docs", "tools"):
            code += read_text(path) + "\n"
    has_model = MODEL_PATTERN.search(code) is not None
    has_api = GEMINI_API_PATTERN.search(code) is not None
    if has_model and has_api:
        return "PASS", "Code uses a Gemma 4 model through the Gemini API", ""
    if LOCAL_ONLY_PATTERN.search(code) and not has_api:
        return "WARN", "Code seems to run Gemma only on your own computer", "The Gemma challenge needs the Gemini API (google-genai). Running Gemma locally does not count."
    return "FAIL", "Could not find a Gemma 4 model ID and the Gemini API in your code", "Call a gemma-4-... model with the google-genai package (see gemma_client.py)."


def check_no_key(root):
    problems = []
    for path in project_files(root):
        if path.name == ".env" or path.stat().st_size > 2_000_000:
            continue  # .env is handled below
        for number, line in enumerate(read_text(path).splitlines(), 1):
            if KEY_PATTERN.search(line):
                problems.append(f"{path.relative_to(root)}:{number} ({KEY_PATTERN.search(line).group()[:4]}{'*' * 35})")
    if problems:
        return "FAIL", "API key found in: " + ", ".join(problems), "Delete the key in Google AI Studio, make a new one, and remove it from the file."
    tracked = git(root, "ls-files")
    if tracked is not None and ".env" in tracked.splitlines():
        return "FAIL", ".env is tracked by git", "Run: git rm --cached .env  then commit. Then delete the key in AI Studio and make a new one."
    if tracked is None and (root / ".env").exists():
        return "WARN", "There is a .env file here and this is not a git repo", "Do not upload or zip your .env file."
    return "PASS", "No API key found in your files", ""


def check_gitignore(root):
    lines = [line.strip() for line in read_text(root / ".gitignore").splitlines()]
    if any(line in (".env", "/.env", ".env*") for line in lines):
        return "PASS", ".gitignore lists .env", ""
    return "FAIL", ".gitignore does not list .env", "Add a line with .env to .gitignore."


def check_readme_sections(root):
    readme = read_text(root / "README.md")
    problems = []
    if not re.search(r"^#+\s.*how to run", readme, re.IGNORECASE | re.MULTILINE):
        problems.append('no "How to run" section (add a heading like "## How to run")')
    images = re.findall(r"!\[[^\]]*\]\(([^)\s]+)", readme) + re.findall(r'<img[^>]+src="([^"]+)"', readme)
    if not images:
        problems.append("no screenshot (add one with ![screenshot](docs/screenshot.png))")
    else:
        local = [i for i in images if not i.startswith(("http://", "https://"))]
        missing = [i for i in local if not (root / i).is_file()]
        if missing:
            problems.append(f"screenshot file not found: {missing[0]}")
    if problems:
        return "FAIL", "README: " + "; ".join(problems), "Fix the README, then run this script again."
    return "PASS", 'README has a "How to run" section and a screenshot', ""


def check_remote(root):
    remotes = git(root, "remote", "-v")
    if remotes and "github.com" in remotes:
        return "WARN", "GitHub remote found. This script cannot check that the repo is public", "Open the repo in a private browser window to confirm it is public."
    return "WARN", "No GitHub remote found", "Push your project to a public GitHub repo."


def run_checks(root):
    results = [
        ("License", check_license(root)),
        ("README model", check_readme_model(root)),
        ("Gemini API", check_gemini_api(root)),
        ("API key safety", check_no_key(root)),
        (".gitignore", check_gitignore(root)),
        ("README sections", check_readme_sections(root)),
        ("GitHub", check_remote(root)),
    ]
    return [(name, *result) for name, result in results]


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    results = run_checks(root)
    for name, status, message, fix in results:
        print(f"{status:<4}  {name}: {message}")
        if fix:
            print(f"      Fix: {fix}")
    print("\nNote: 'Built today' is checked by judges, not by this script.")
    failed = [name for name, status, *_ in results if status == "FAIL"]
    print("\nFAILED: " + ", ".join(failed) if failed else "\nNo FAILs. Check the WARN lines, then submit.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
