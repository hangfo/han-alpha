from pathlib import Path


def test_ci_uses_same_hash_locked_full_verification_contract() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text()
    assert "--require-hashes -r requirements-dev.lock" in workflow
    assert "--no-build-isolation" in workflow
    assert "./scripts/preflight.sh" in workflow
    assert "./scripts/verify_all.sh" in workflow
    assert "pip check" in workflow
    assert "pip install -e '.[dev]'" not in workflow


def test_project_tree_is_generated_from_git_content_without_caches() -> None:
    generator = Path("scripts/generate_project_tree.sh").read_text()
    tree = Path("PROJECT_TREE.txt").read_text()
    assert "git ls-files --cached --others --exclude-standard" in generator
    for forbidden in ("__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"):
        assert forbidden not in tree
    assert "./src/hanalpha/simulation/engine.py" in tree
    assert "./src/hanalpha/experiments/runner.py" in tree
