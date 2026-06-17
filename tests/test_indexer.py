"""Tests for backend.indexer — file_tree and signatures modules.

No external services needed: all tests operate on tmp_path fixtures.
"""

from pathlib import Path

from backend.indexer.file_tree import build_file_tree
from backend.indexer.signatures import build_codebase_map

# ---------------------------------------------------------------------------
# build_file_tree
# ---------------------------------------------------------------------------


def test_file_tree_lists_source_files(tmp_path: Path) -> None:
    """Regular source files appear in the tree output."""
    (tmp_path / "main.py").write_text("print('hello')")
    (tmp_path / "utils.py").write_text("def helper(): pass")
    tree = build_file_tree(str(tmp_path))
    assert "main.py" in tree
    assert "utils.py" in tree


def test_file_tree_skips_always_skip_dirs(tmp_path: Path) -> None:
    """node_modules, __pycache__, .git etc. are never listed."""
    for skip_dir in ("node_modules", "__pycache__", ".git", ".venv", "dist"):
        d = tmp_path / skip_dir
        d.mkdir()
        (d / "file.py").write_text("x = 1")
    (tmp_path / "app.py").write_text("x = 1")

    tree = build_file_tree(str(tmp_path))
    assert "node_modules" not in tree
    assert "__pycache__" not in tree
    assert ".git" not in tree
    assert ".venv" not in tree
    assert "dist" not in tree
    assert "app.py" in tree


def test_file_tree_skips_pyc_and_map_files(tmp_path: Path) -> None:
    """Compiled/generated file extensions are excluded."""
    (tmp_path / "module.pyc").write_bytes(b"\x00")
    (tmp_path / "bundle.min.js").write_text("!function(){}")
    (tmp_path / "source.py").write_text("x = 1")

    tree = build_file_tree(str(tmp_path))
    assert "module.pyc" not in tree
    assert "bundle.min.js" not in tree
    assert "source.py" in tree


def test_file_tree_respects_noodcodeignore(tmp_path: Path) -> None:
    """.noodcodeignore entries exclude matching directories."""
    secret_dir = tmp_path / "private"
    secret_dir.mkdir()
    (secret_dir / "secret.py").write_text("password = 'hunter2'")
    (tmp_path / "public.py").write_text("x = 1")
    (tmp_path / ".noodcodeignore").write_text("private\n")

    tree = build_file_tree(str(tmp_path))
    assert "private" not in tree
    assert "public.py" in tree


def test_file_tree_truncates_at_max_files(tmp_path: Path) -> None:
    """build_file_tree stops listing after max_files and adds a truncation notice."""
    for i in range(20):
        (tmp_path / f"file{i:03d}.py").write_text(f"x = {i}")

    tree = build_file_tree(str(tmp_path), max_files=5)
    lines = tree.splitlines()
    assert any("truncated" in line for line in lines)
    # Only 5 real files + the truncation line
    real_lines = [l for l in lines if "truncated" not in l]
    assert len(real_lines) == 5


def test_file_tree_empty_workspace(tmp_path: Path) -> None:
    """Empty workspace returns empty string (no crash)."""
    result = build_file_tree(str(tmp_path))
    assert result == ""


# ---------------------------------------------------------------------------
# build_codebase_map (Python signature extraction)
# ---------------------------------------------------------------------------


def test_codebase_map_extracts_python_functions(tmp_path: Path) -> None:
    """Python function and class signatures appear in the map."""
    src = tmp_path / "calc.py"
    src.write_text(
        "class Calculator:\n"
        "    def add(self, a, b):\n"
        "        return a + b\n"
        "\n"
        "def subtract(a, b):\n"
        "    return a - b\n"
    )
    file_tree = build_file_tree(str(tmp_path))
    cmap = build_codebase_map(str(tmp_path), file_tree)
    assert "calc.py" in cmap
    assert "add" in cmap
    assert "subtract" in cmap
    assert "Calculator" in cmap


def test_codebase_map_extracts_async_functions(tmp_path: Path) -> None:
    """async def signatures are captured."""
    (tmp_path / "server.py").write_text(
        "async def handle_request(req):\n    pass\n" "async def startup():\n    pass\n"
    )
    file_tree = build_file_tree(str(tmp_path))
    cmap = build_codebase_map(str(tmp_path), file_tree)
    assert "handle_request" in cmap
    assert "startup" in cmap


def test_codebase_map_respects_max_tokens(tmp_path: Path) -> None:
    """Total map stays within the token budget (truncation marker appears when needed)."""
    # Create many files to force budget overflow
    for i in range(30):
        (tmp_path / f"module{i:03d}.py").write_text(
            "\n".join(f"def func_{j}(): pass" for j in range(20))
        )

    file_tree = build_file_tree(str(tmp_path))
    cmap = build_codebase_map(str(tmp_path), file_tree, max_tokens=100)
    assert "truncated" in cmap


def test_codebase_map_files_without_supported_extension(tmp_path: Path) -> None:
    """Files without regex patterns are listed by path alone (no crash)."""
    (tmp_path / "README.md").write_text("# Project\nSome docs")
    (tmp_path / "Makefile").write_text("build:\n\tpython setup.py")
    file_tree = build_file_tree(str(tmp_path))
    cmap = build_codebase_map(str(tmp_path), file_tree)
    assert "README.md" in cmap
    assert "Makefile" in cmap


def test_codebase_map_empty_workspace(tmp_path: Path) -> None:
    """Empty workspace produces empty map without raising."""
    file_tree = build_file_tree(str(tmp_path))
    cmap = build_codebase_map(str(tmp_path), file_tree)
    assert cmap == ""
