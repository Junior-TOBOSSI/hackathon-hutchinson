"""SCI-02 job installer: definition derived from the proven template, code files only."""

from types import SimpleNamespace

from mlops.training.install_job import code_files, job_settings


def test_job_settings_come_from_the_template_without_schedule_or_retry():
    template = {
        "name": "hovis-quality-industrial-training",
        "schedule": {"quartz_cron_expression": "0 0 * * * ?"},
        "tasks": [
            {
                "task_key": "t",
                "retry_on_timeout": True,
                "max_retries": 3,
                "notebook_task": {
                    "notebook_path": "/Shared/ARGOS-POC/run_volume_script",
                    "base_parameters": {"script": "old", "args": "[1]"},
                },
                "environment_key": "e",
            }
        ],
        "environments": [
            {"environment_key": "e", "spec": {"client": "3", "dependencies": ["old"]}}
        ],
    }
    spec = SimpleNamespace(
        job={"name": "hovis-workstation-training", "script": "/Volumes/x/run.py"},
        compute={"environment": ["numpy==1.26.4", "ultralytics==8.4.219"]},
    )
    s = job_settings(template, spec)
    assert s["name"] == "hovis-workstation-training" and "schedule" not in s
    task = s["tasks"][0]
    assert task["max_retries"] == 0 and "retry_on_timeout" not in task
    assert task["notebook_task"]["notebook_path"] == "/Shared/ARGOS-POC/run_volume_script"
    assert task["notebook_task"]["base_parameters"] == {"script": "/Volumes/x/run.py", "args": "[]"}
    assert s["environments"][0]["spec"]["dependencies"] == ["numpy==1.26.4", "ultralytics==8.4.219"]
    assert template["name"] == "hovis-quality-industrial-training"  # template untouched


def test_only_code_files_of_the_runner_are_uploaded():
    files = [f.as_posix() for f in code_files("mlops/pipelines/workstation/run_pipeline.py")]
    assert any(f.endswith("mlops/pipelines/workstation/run_pipeline.py") for f in files)
    assert any(f.endswith("kit/usecases/workstation/model.py") for f in files)
    assert any(f.endswith("mlops/__init__.py") for f in files)
    assert not any(f.endswith((".pyc", ".pt", ".jpg", ".png", ".zip", ".sqlite3")) for f in files)
