"""Extract the symbols a diff actually references.

Embedding similarity is good at "find me code that looks like this" but bad
at "find me the definition of this exact function/type". A senior reviewer
catches cross-file bugs by resolving the symbols a change touches (a called
function, a type, an imported name) and reading their definitions. This module
pulls those identifiers out of a diff so we can fetch their definitions
directly instead of hoping fuzzy retrieval surfaces them.
"""

import re

# Identifiers that are language keywords or so generic that resolving their
# "definition" would only add noise. Kept deliberately small and shared across
# Python / JS / TS rather than perfectly language-specific.
STOPWORDS = frozenset(
    {
        # control flow / keywords
        "if",
        "else",
        "elif",
        "for",
        "while",
        "return",
        "import",
        "from",
        "as",
        "def",
        "class",
        "const",
        "let",
        "var",
        "function",
        "type",
        "interface",
        "enum",
        "export",
        "default",
        "async",
        "await",
        "yield",
        "try",
        "except",
        "catch",
        "finally",
        "throw",
        "raise",
        "with",
        "in",
        "is",
        "not",
        "and",
        "or",
        "of",
        "new",
        "this",
        "self",
        "super",
        "true",
        "false",
        "none",
        "null",
        "undefined",
        "void",
        "typeof",
        "instanceof",
        "extends",
        "implements",
        "public",
        "private",
        "protected",
        "static",
        "readonly",
        "switch",
        "case",
        "break",
        "continue",
        "do",
        "delete",
        "pass",
        "lambda",
        "global",
        "nonlocal",
        # ubiquitous generic names that would match definitions everywhere
        "data",
        "value",
        "values",
        "item",
        "items",
        "name",
        "names",
        "props",
        "state",
        "result",
        "results",
        "response",
        "request",
        "error",
        "err",
        "index",
        "key",
        "keys",
        "id",
        "ids",
        "args",
        "kwargs",
        "params",
        "options",
        "config",
        "context",
        "ctx",
        "obj",
        "arr",
        "list",
        "dict",
        "str",
        "int",
        "bool",
        "float",
        "len",
        "print",
        "console",
        "log",
        "map",
        "filter",
        "reduce",
        "forEach",
        "length",
        "push",
        "get",
        "set",
    }
)

_VALID_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CALL = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_PASCAL = re.compile(r"\b([A-Z][A-Za-z0-9_]+)\b")
_IMPORT_BLOCK = re.compile(r"import\s*(?:type\s*)?\{([^}]*)\}")
_PY_IMPORT = re.compile(r"(?:from\s+\S+\s+import|import)\s+(.+)")


def _added_lines(diff: str) -> list[str]:
    lines = []
    for line in diff.splitlines():
        if line.startswith("+++"):
            continue
        if line.startswith("+"):
            lines.append(line[1:])
    return lines


def _keep(name: str) -> bool:
    return (
        len(name) >= 3
        and _VALID_IDENTIFIER.match(name) is not None
        and name.lower() not in STOPWORDS
    )


def extract_referenced_symbols(diff: str, max_symbols: int = 30) -> list[str]:
    """Return identifiers referenced by the diff's added lines, ranked.

    Priority order, because these are the symbols whose definitions most often
    explain a bug: imported names, then types (PascalCase), then called
    functions, then any remaining identifiers. Returned in priority order and
    de-duplicated, capped at ``max_symbols``.
    """
    added = _added_lines(diff)

    imported: list[str] = []
    types: list[str] = []
    called: list[str] = []
    other: list[str] = []

    for line in added:
        block = _IMPORT_BLOCK.search(line)
        if block:
            for raw in block.group(1).split(","):
                token = raw.strip().split(" as ")[0].strip()
                if token and _keep(token):
                    imported.append(token)
        py_import = _PY_IMPORT.search(line.strip())
        if py_import and ("import" in line):
            for raw in py_import.group(1).split(","):
                token = raw.strip().split(" as ")[0].strip().strip("()")
                if token and _keep(token):
                    imported.append(token)

        for name in _CALL.findall(line):
            if _keep(name):
                called.append(name)
        for name in _PASCAL.findall(line):
            if _keep(name):
                types.append(name)
        for name in _IDENTIFIER.findall(line):
            if _keep(name):
                other.append(name)

    seen: set[str] = set()
    ordered: list[str] = []
    for group in (imported, types, called, other):
        for name in group:
            if name not in seen:
                seen.add(name)
                ordered.append(name)
            if len(ordered) >= max_symbols:
                return ordered
    return ordered


def build_definition_pattern(symbols: list[str]) -> str | None:
    """Build a Postgres regex that matches definitions of any given symbol.

    Matches a definition keyword followed by one of the symbol names on a word
    boundary, e.g. ``def foo`` / ``class Foo`` / ``const foo`` / ``type Foo``.
    Returns ``None`` when there are no symbols to look for.
    """
    if not symbols:
        return None
    keywords = r"def|class|function|const|let|var|type|interface|enum|struct"
    names = "|".join(re.escape(s) for s in symbols)
    return rf"\y({keywords})\s+({names})\y"
