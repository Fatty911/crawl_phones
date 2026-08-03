from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_plan_agent_boundary.py"


def test_plan_credentials_are_not_available_to_phone_python_paths():
    spec = importlib.util.spec_from_file_location("plan_agent_boundary_phones", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    errors = module.validate_repository(ROOT)
    assert errors == [], "\\n".join(errors)


def test_validator_rejects_generic_plan_secret_in_run(tmp_path):
    spec = importlib.util.spec_from_file_location("plan_agent_boundary_phones_bad", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    workflow = workflow_dir / "bad.yml"
    workflow.write_text(
        """name: bad
jobs:
  bad:
    runs-on: ubuntu-latest
    steps:
      - name: Bad Agent
        run: opencode run --pure --agent plan --model acme/model --dir \"$RUNNER_TEMP/opencode-agent\" --file prompt.md \"${{ secrets.ACME_CODINGPLAN_API_KEY }}\" > out.txt
""",
        encoding="utf-8",
    )
    errors = []
    module._check_workflow(workflow, errors, tmp_path)
    assert any("ACME_CODINGPLAN_API_KEY" in error and "env" in error for error in errors)


def test_validator_recursively_rejects_plan_secret_in_python(tmp_path):
    spec = importlib.util.spec_from_file_location("plan_agent_boundary_phones_nested", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    nested = tmp_path / "scripts" / "nested"
    nested.mkdir(parents=True)
    (nested / "worker.py").write_text(
        "PLAN = 'ACMEPLAN_API_KEY'\n",
        encoding="utf-8",
    )
    errors = module.validate_repository(tmp_path)
    assert any("worker.py" in error and "ACMEPLAN_API_KEY" in error for error in errors)
