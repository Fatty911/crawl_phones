import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPECS = {
    "crawl-sim": ("filteredJson", 20, "array", "/tmp/cnb-baseline/baseline.json"),
    "crawl_cars": ("latestJson", 10000, "array", "/tmp/cnb-baseline/latest.json"),
    "crawl_laptops": ("latestJson", 50, "items", "baseline/laptops-latest.json"),
    "crawl_ac": ("latestJson", 50, "items", "baseline/ac-latest.json"),
    "crawl_phones": ("latestJson", 1, "array", "/tmp/phones-pages-baseline.json"),
    "crawl_vps_promotions": ("price_history", 1, "history", "site/data/price_history.json"),
}


def baseline_stages():
    workflow = yaml.safe_load((ROOT / ".cnb.yml").read_text(encoding="utf-8"))
    stages = []
    for pipelines in workflow["main"].values():
        if not isinstance(pipelines, list):
            continue
        for pipeline in pipelines:
            for stage in pipeline.get("stages", []):
                if stage["name"] in ("获取线上发布基线", "下载线上发布数据（车系ID 来源）"):
                    stages.append(stage)
    return stages


def test_all_baseline_entrypoints_require_latest_complete_immutable_release():
    stages = baseline_stages()
    assert len(stages) == (3 if ROOT.name == "crawl_cars" else 2)
    for stage in stages:
        script = stage["script"]
        assert "download_verified_release.py --repo Fatty911/" + ROOT.name + " --no-legacy" in script
        assert script.index("download_verified_release.py") < script.index("prepare_cnb_pages.py") < script.index("shutil.copyfile")
        assert "--manifest /tmp/cnb-verified-baseline-assets/manifest.json" in script
        assert "curl " not in script and "docs/data/latest.json" not in script
        assert "|| true" not in script
        shell = shutil.which("bash")
        if shell:
            subprocess.run([shell, "-n", "-c", script], check=True)


def exercise_baseline(tmp_path, count):
    key, minimum, shape, target_name = SPECS[ROOT.name]
    rows = [{"identity": str(i), "source_id": str(i), "atomic_source_names": ["fixture"], "商品": "真实保留字段"}
            for i in range(count)]
    payload = {"items": rows, "generated_at": "2026-01-01T00:00:00Z"} if shape == "items" else rows
    verified = tmp_path / "verified"
    data = verified / "data"
    data.mkdir(parents=True)
    selected = data / ("price_history.json" if shape == "history" else "complete.json")
    encoded = json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")
    selected.write_bytes(encoded)
    files = {"latestJson": "data/complete.json", "filteredJson": "data/complete.json"}
    if ROOT.name == "crawl-sim":
        # The in-display subset must never substitute for the full raw baseline.
        files["latestJson"] = "data/shown-only.json"
        (data / "shown-only.json").write_text("[]")
    (data / "manifest.json").write_text(json.dumps({"files": files}), encoding="utf-8")
    if shape == "history":
        (tmp_path / "state").mkdir()
        (tmp_path / "state/history.json").write_text('[{"identity":"stale-state"}]')
    stage = baseline_stages()[0]
    script = stage["script"].split("python - <<'PY'\n", 1)[1].split("\nPY", 1)[0]
    script = script.replace("/tmp/cnb-verified-baseline-site", verified.as_posix())
    target = tmp_path / "baseline-output.json"
    script = script.replace(target_name, target.as_posix())
    process = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, text=True, capture_output=True)
    return process, target, encoded


def test_verified_baseline_preserves_full_payload_bytes_identity_and_history_priority(tmp_path):
    minimum = SPECS[ROOT.name][1]
    process, target, expected = exercise_baseline(tmp_path, minimum)
    assert process.returncode == 0, process.stderr
    assert target.read_bytes() == expected
    if ROOT.name == "crawl_vps_promotions":
        assert (tmp_path / "state/history.json").read_bytes() == expected


def test_empty_or_undersized_verified_baseline_fails_instead_of_using_old_data(tmp_path):
    minimum = SPECS[ROOT.name][1]
    process, target, _ = exercise_baseline(tmp_path, minimum - 1)
    assert process.returncode != 0
    assert "verified baseline incomplete" in process.stderr
    assert not target.exists()
