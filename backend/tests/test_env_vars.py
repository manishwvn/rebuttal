"""Every environment variable the backend reads must be documented in .env.example (or explicitly allowlisted)."""
import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

# Read by the code but intentionally not in .env.example. Add a reason for every entry.
ALLOWLIST: dict[str, str] = {
    "LANGFUSE_HOST": "deprecated alias of LANGFUSE_BASE_URL, mentioned in a comment in .env.example",
}


def _env_names_read() -> dict[str, str]:
    """Literal names passed to os.getenv / os.environ[...] / os.environ.get, plus the tuples that feed
    the loop in tracing.py (`for key in ("LANGFUSE_...")`)."""
    found: dict[str, str] = {}
    for path in (BACKEND / "rebuttal").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                owner = ast.unparse(node.func.value)
                if (owner == "os" and node.func.attr == "getenv") or (
                    owner == "os.environ" and node.func.attr in ("get", "pop")
                ):
                    if node.args and isinstance(node.args[0], ast.Constant):
                        name = node.args[0].value
            elif isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ":
                if isinstance(node.slice, ast.Constant):
                    name = node.slice.value
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                # names looked up indirectly, e.g. os.getenv(key) over a tuple of literals
                if re.fullmatch(r"(LANGFUSE|REBUTTAL|PAYPAL)_[A-Z_]+", node.value):
                    name = node.value
            if isinstance(name, str):
                found.setdefault(name, f"{path.relative_to(BACKEND)}:{node.lineno}")
    return found


def _documented() -> set[str]:
    text = (BACKEND / ".env.example").read_text()
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", text, flags=re.MULTILINE))


def test_every_env_var_read_is_documented_in_env_example():
    documented = _documented() | set(ALLOWLIST)
    missing = {n: where for n, where in _env_names_read().items() if n not in documented}
    assert not missing, f"add these to backend/.env.example (or ALLOWLIST with a reason): {missing}"


def test_the_scan_sees_the_known_variables():
    names = _env_names_read()
    assert {"PAYPAL_ENV", "REBUTTAL_MOCK", "LANGFUSE_PUBLIC_KEY", "DATABASE_URL"} <= set(names)
