"""Deterministic retrieval and spectrum-based localization for polyglot projects."""

from __future__ import annotations

import ast
import math
import re
from collections import Counter
from pathlib import Path

from .repo import SOURCE_EXTENSIONS, files, read_text


def tokenize(text: str) -> list[str]:
    return re.findall(
        r"\w+", re.sub(r"([a-z])([A-Z])", r"\1 \2", text).replace("_", " ").lower()
    )


def coverage_spectra(
    report: dict, failing_contexts: list[str], passing_contexts: list[str]
) -> dict:
    """Convert coverage.py JSON --show-contexts into observed line spectra."""
    failed, passed = set(failing_contexts), set(passing_contexts)
    if not failed or failed.intersection(passed):
        raise ValueError(
            "Provide nonempty, disjoint failing/passing test context names"
        )
    rows, observed = [], set()
    for filename, data in report.get("files", {}).items():
        for line, contexts in data.get("contexts", {}).items():
            seen = set(contexts)
            observed.update(seen)
            rows.append(
                {
                    "symbol": f"{filename}:{line}",
                    "failed": len(seen & failed),
                    "passed": len(seen & passed),
                }
            )
    if not rows or not (failed | passed).issubset(observed):
        raise ValueError(
            "Coverage report lacks supplied test contexts; export JSON with --show-contexts"
        )
    return {"spectra": rows, "total_failed": len(failed), "total_passed": len(passed)}


def bm25(root: Path, query: str, limit: int = 10) -> list[dict]:
    docs = []
    for path in files(root):
        try:
            terms = tokenize(
                path.relative_to(root).as_posix() + "\n" + read_text(path, 200000)
            )
            docs.append((path, Counter(terms), len(terms)))
        except (OSError, ValueError):
            continue
    average = sum(d[2] for d in docs) / max(1, len(docs)) or 1
    query_terms = set(tokenize(query))
    frequencies = {term: sum(term in d[1] for d in docs) for term in query_terms}
    results = []
    for path, counts, length in docs:
        score = 0.0
        for term in query_terms:
            freq = counts[term]
            idf = math.log(
                1 + (len(docs) - frequencies[term] + 0.5) / (frequencies[term] + 0.5)
            )
            score += idf * freq * 2.5 / (freq + 1.5 * (0.25 + 0.75 * length / average))
        if score:
            results.append(
                {"path": path.relative_to(root).as_posix(), "score": round(score, 4)}
            )
    return sorted(results, key=lambda x: x["score"], reverse=True)[:limit]


def _python_symbols(path: Path, root: Path, query: str) -> list[dict]:
    result = []
    try:
        tree = ast.parse(read_text(path))
    except (OSError, ValueError, SyntaxError):
        return result
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and query.lower() in node.name.lower()
        ):
            calls = sorted(
                {ast.unparse(c.func) for c in ast.walk(node) if isinstance(c, ast.Call)}
            )
            result.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "symbol": node.name,
                    "line": node.lineno,
                    "end_line": node.end_lineno,
                    "kind": type(node).__name__,
                    "calls": calls[:50],
                }
            )
    return result


_SYMBOL = re.compile(
    r"^\s*(?:(?:public|private|protected|internal|static|abstract|final|"
    r"export|default|async|override|virtual|sealed|partial)\s+)*"
    r"(?P<kind>class|interface|struct|enum|record|trait|module|namespace|"
    r"function|func|fn|def|sub|type)\s+(?P<name>[A-Za-z_$][\w$.:!?-]*)",
    re.IGNORECASE,
)
_C_STYLE_FUNCTION = re.compile(
    r"^\s*(?:[A-Za-z_][\w:<>,\[\]*&? ]*\s+)(?P<name>[A-Za-z_]\w*)\s*\([^;]*\)\s*(?:\{|=>)",
)
_CALL = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\(")
_CALL_KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "sizeof", "new"}


def _generic_symbols(path: Path, root: Path, query: str) -> list[dict]:
    try:
        lines = read_text(path).splitlines()
    except (OSError, ValueError):
        return []
    result = []
    for line_no, text in enumerate(lines, 1):
        match = _SYMBOL.match(text)
        kind = match.group("kind") if match else "function"
        if not match:
            match = _C_STYLE_FUNCTION.match(text)
        if not match:
            continue
        name = match.group("name")
        if query.lower() not in name.lower():
            continue
        calls = sorted(
            {
                call
                for call in _CALL.findall(text)
                if call.lower() not in _CALL_KEYWORDS and call != name
            }
        )
        result.append(
            {
                "path": path.relative_to(root).as_posix(),
                "symbol": name,
                "line": line_no,
                "end_line": line_no,
                "kind": kind,
                "calls": calls,
                "approximate": True,
            }
        )
    return result


def symbols(root: Path, query: str = "") -> list[dict]:
    """Find declarations in supported text languages; Python uses a real AST."""
    result = []
    for path in files(root):
        if path.suffix not in SOURCE_EXTENSIONS:
            continue
        if path.suffix == ".py":
            result.extend(_python_symbols(path, root, query))
        else:
            result.extend(_generic_symbols(path, root, query))
        if len(result) >= 300:
            break
    return result[:300]


def localize(
    spectra: list[dict], total_failed: int, total_passed: int, formula: str = "ochiai"
) -> list[dict]:
    if total_failed < 1 or total_passed < 0:
        raise ValueError(
            "Localization requires at least one failing test and nonnegative passing count"
        )
    if formula not in {"ochiai", "tarantula", "dstar"}:
        raise ValueError("Unknown SBFL formula")
    result = []
    for row in spectra:
        failed, passed = row["failed"], row["passed"]
        if not 0 <= failed <= total_failed or not 0 <= passed <= total_passed:
            raise ValueError("Spectrum counts exceed test totals")
        if formula == "ochiai":
            score = (
                failed / math.sqrt(total_failed * (failed + passed)) if failed else 0
            )
        elif formula == "tarantula":
            f = failed / total_failed
            p = passed / total_passed if total_passed else 0
            score = f / (f + p) if f + p else 0
        else:
            denominator = passed + total_failed - failed
            score = (
                failed**2 / denominator if denominator else float(total_failed**2 + 1)
            )
        result.append({**row, "score": round(score, 6)})
    return sorted(result, key=lambda row: row["score"], reverse=True)
