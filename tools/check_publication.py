"""Offline publication checks. Heuristic checks are not a proof that no secret exists."""
import ast
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "provider_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-ant-[A-Za-z0-9_-]{16,})"),
    "telegram_token": re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b"),
    "ipv4_address": re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"),
    "cloud_instance_id": re.compile(r"\bi-[0-9a-f]{8,17}\b"),
    "email_address": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "home_directory": re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+/"),
}
ALLOWED_EXTENSIONS = {".md", ".py", ".json", ".toml", ".txt"}
ALLOWED_DOTFILES = {".gitignore", ".gitattributes"}
PACKAGE_IMPORTS = {"dataclasses", "datetime", "math", "json", "pathlib"}


def check() -> dict:
    findings = []
    files = []
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT)
        # Repository metadata is never part of published file content.
        if ".git" in rel.parts:
            continue
        if path.is_symlink():
            findings.append({"file": str(rel), "rule": "symlink_forbidden"})
            continue
        if path.is_dir():
            if path.name in {"__pycache__", ".venv"}:
                findings.append({"file": str(rel), "rule": "private_or_generated_directory"})
            continue
        files.append(path)
        if path.name not in ALLOWED_DOTFILES and path.suffix not in ALLOWED_EXTENSIONS:
            findings.append({"file": str(rel), "rule": "unexpected_file_type"})
        if path.name.startswith(".env"):
            findings.append({"file": str(rel), "rule": "environment_file_forbidden"})
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append({"file": str(rel), "rule": "non_text_file"})
            continue
        for rule, pattern in PATTERNS.items():
            for match in pattern.finditer(content):
                findings.append({"file": str(rel), "rule": rule,
                                 "line": content[:match.start()].count("\n") + 1})
        if path.suffix == ".md":
            for link in re.findall(r"\]\(([^\s)]+)\)", content):
                if "://" in link or link.startswith("#"):
                    continue
                target = (path.parent / link.split("#")[0]).resolve()
                if not target.is_relative_to(ROOT) or not target.exists():
                    findings.append({"file": str(rel), "rule": "broken_or_external_local_link", "link": link})
        if path.suffix == ".py":
            tree = ast.parse(content, filename=str(rel))
            if rel.parts[0] == "stock_ai_portfolio":
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        modules = [n.name.split(".")[0] for n in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.level == 0:
                        modules = [(node.module or "").split(".")[0]]
                    else:
                        modules = []
                    for module in modules:
                        if module not in PACKAGE_IMPORTS:
                            findings.append({"file": str(rel), "rule": "unexpected_runtime_import", "module": module})
    manifest = json.loads((ROOT / "reference/manifest.json").read_text())
    blocks = {}
    pattern = r"^### `([^`]+)` L(\d+)–L(\d+)\n\n```(?:python|bash)\n(.*?)^```$"
    for path in (ROOT / "reference").glob("*.md"):
        for source, start, end, code in re.findall(pattern, path.read_text(), flags=re.S | re.M):
            blocks[(source, int(start), int(end))] = hashlib.sha256(code.encode()).hexdigest()
    for entry in manifest:
        key = (entry["source_file"], entry["start_line"], entry["end_line"])
        if blocks.get(key) != entry["excerpt_sha256"]:
            findings.append({"file": "reference/manifest.json", "rule": "excerpt_hash_mismatch", "source": key[0]})
    if len(blocks) != len(manifest):
        findings.append({"file": "reference/manifest.json", "rule": "excerpt_count_mismatch"})
    return {"status": "PASS" if not findings else "FAIL", "files_scanned": len(files),
            "source_excerpts_checked": len(manifest), "findings": findings,
            "limits": "Heuristic patterns, runtime import allowlist and local links only; manual review still required."}


if __name__ == "__main__":
    result = check()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["status"] == "PASS" else 1)
