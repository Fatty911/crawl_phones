from pathlib import Path
import yaml


def test_pages_consumers_share_canonical_group_without_canceling_active_deploy():
    root = Path(__file__).parents[1] / '.github/workflows'
    canonical = yaml.safe_load((root / 'cnb-pages.yml').read_text(encoding='utf-8'))['concurrency']
    assert canonical['cancel-in-progress'] is False
    count = 0
    for name in ('cnb-pages.yml', 'deploy-pages.yml', 'deploy-frontend.yml', 'frontend-deploy.yml', 'pages-deploy.yml'):
        path = root / name
        if not path.exists():
            continue
        workflow = yaml.safe_load(path.read_text(encoding='utf-8'))
        for job in workflow['jobs'].values():
            if any(str(step.get('uses', '')).startswith('actions/deploy-pages@') for step in job.get('steps', [])):
                concurrency = job.get('concurrency', workflow.get('concurrency'))
                assert concurrency == canonical, f'{name} can race with the canonical CNB deployment'
                count += 1
    assert count >= 2
