"""Unit tests for Shift on Shift bootstrap wiring.

Static checks of seed playbooks, job templates, registry and selector entries,
plus a behavioral run of the preflight overlay. The full preflight to generated
repo path is covered by ``integration_bootstrap_shift_on_shift``.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
JT_DIR = ROOT / "roles/bootstrap_controller/files/job_templates"
SEED_DIR = ROOT / "roles/bootstrap_generate_playbook_repo/files/playbooks/shift_on_shift"
ACTIONS = ("validate", "deploy", "status", "scale", "update", "access", "delete")
OVERLAY = ROOT / "roles/bootstrap_generate_env_vars/files/overlay_preflight_component_values.py"


def _yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _survey(action: str) -> dict:
    jt = _yaml(JT_DIR / f"ado-shift-on-shift-{action}-bootstrap.jt.yml")["controller_templates"][0]
    return {item["variable"]: item for item in jt["survey_spec"]["spec"]}


@pytest.mark.parametrize("action", ACTIONS)
def test_job_template_points_at_seed(action: str) -> None:
    jt = _yaml(JT_DIR / f"ado-shift-on-shift-{action}-bootstrap.jt.yml")["controller_templates"][0]
    assert jt["playbook"] == f"playbooks/shift_on_shift/ado-shift-on-shift-{action}-bootstrap.yml"
    assert (SEED_DIR / f"ado-shift-on-shift-{action}-bootstrap.yml").is_file()
    assert jt["survey_enabled"] is True
    assert "env" in _survey(action)


@pytest.mark.parametrize("action", ACTIONS)
def test_seed_loads_component_vars_and_vault(action: str) -> None:
    play = _yaml(SEED_DIR / f"ado-shift-on-shift-{action}-bootstrap.yml")[0]
    assert play["vars"]["component"] == "shift_on_shift"
    files = " ".join(play["vars_files"])
    for name in ("infra_config_vars.yml", "vault_openshift.yml", "vault_{{ component }}.yml", "vars_{{ component }}.yml"):
        assert name in files
    assert set(play["environment"]) == {"K8S_AUTH_HOST", "K8S_AUTH_API_KEY", "K8S_AUTH_VERIFY_SSL"}
    role = play["tasks"][0]["ansible.builtin.include_role"]["name"]
    if action == "validate":
        assert role == "infra.automation_development_office.ocp_hcp_kubevirt_prereqs"
    else:
        assert role == "infra.automation_development_office.ocp_hcp_kubevirt_cluster"
        assert play["tasks"][0]["vars"]["ocp_hcp_kubevirt_cluster_action"] == action


def test_single_target_actions_require_cluster_name() -> None:
    for action in ("scale", "update", "access", "delete"):
        assert _survey(action)["shift_on_shift_cluster_name"]["required"] is True
    for action in ("validate", "deploy", "status"):
        assert _survey(action)["shift_on_shift_cluster_name"]["required"] is False


def test_delete_survey_requires_typed_confirmation() -> None:
    survey = _survey("delete")
    assert survey["shift_on_shift_confirm_delete"]["required"] is True
    assert survey["shift_on_shift_confirm_delete"]["type"] == "text"
    assert survey["shift_on_shift_delete_namespace"]["default"] == "false"


def test_update_survey_requires_confirmation_and_defaults_safe() -> None:
    survey = _survey("update")
    assert survey["shift_on_shift_confirm_update"]["default"] == "false"
    assert survey["shift_on_shift_force_upgrade"]["default"] == "false"
    assert survey["shift_on_shift_update_nodepools"]["default"] == "false"


def test_controller_map_lists_every_job_template() -> None:
    text = (ROOT / "roles/bootstrap_controller/tasks/generate_aap_configs.yml").read_text(encoding="utf-8")
    assert "      shift_on_shift:\n" in text
    for action in ACTIONS:
        assert f"ado-shift-on-shift-{action}-bootstrap.jt.yml" in text


def test_playbook_repo_registers_seeds_under_openshift() -> None:
    defaults = _yaml(ROOT / "roles/bootstrap_generate_playbook_repo/defaults/main.yml")
    assert "shift_on_shift" in defaults["bootstrap_generate_playbook_repo_component_map"]["openshift"]
    dests = {
        item["dest"]
        for item in defaults["bootstrap_generate_playbook_repo_generated_playbooks"]
        if item.get("app") == "shift_on_shift"
    }
    assert dests == {f"playbooks/shift_on_shift/ado-shift-on-shift-{a}-bootstrap.yml" for a in ACTIONS}


def test_env_vars_selectors_and_registry() -> None:
    defaults = _yaml(ROOT / "roles/bootstrap_generate_env_vars/defaults/main.yml")
    assert "shift_on_shift" in defaults["generate_env_vars_components"]
    assert "shift_on_shift" in defaults["bootstrap_generate_env_vars_preflight_ui_openshift_apps"]
    registry = _yaml(ROOT / "roles/bootstrap_resolve_component/files/components_defaults.yml")
    entry = registry["components_defaults"]["shift_on_shift"]
    assert entry["component_name"] == "shift_on_shift"
    assert entry["skip_operator_install"] is True


def test_templates_split_secrets_into_vault() -> None:
    vars_tpl = (ROOT / "roles/bootstrap_generate_env_vars/templates/component_vars.yml.j2").read_text(encoding="utf-8")
    vault_tpl = (ROOT / "roles/bootstrap_generate_env_vars/templates/component_vault.yml.j2").read_text(encoding="utf-8")
    assert "component_name == 'shift_on_shift'" in vars_tpl
    assert "'rejectattr', 'key', 'equalto', 'pull_secret'" in vars_tpl
    assert "shift_on_shift_pull_secrets:" in vault_tpl
    assert "shift_on_shift_pull_secrets" not in vars_tpl


def _seed_vars(action: str) -> dict:
    seed = _yaml(SEED_DIR / f"ado-shift-on-shift-{action}-bootstrap.yml")[0]
    return seed["tasks"][0]["vars"]


def test_install_prerequisites_reaches_validate_and_deploy() -> None:
    vars_tpl = (ROOT / "roles/bootstrap_generate_env_vars/templates/component_vars.yml.j2").read_text(encoding="utf-8")
    assert "shift_on_shift_install_prerequisites:" in vars_tpl
    assert "shift_on_shift_metallb_address_pools:" in vars_tpl
    deploy = _seed_vars("deploy")
    assert "shift_on_shift_install_prerequisites" in deploy["ocp_hcp_kubevirt_cluster_install_prerequisites"]
    assert "shift_on_shift_metallb_address_pools" in deploy["ocp_hcp_kubevirt_cluster_metallb_address_pools"]
    validate = _seed_vars("validate")
    # Validate reports installable items as planned only when deploy will install them.
    assert "shift_on_shift_install_prerequisites" in validate["ocp_hcp_kubevirt_prereqs_install_planned"]
    assert "shift_on_shift_install_prerequisites" in validate["ocp_hcp_kubevirt_prereqs_wildcard_remediation_planned"]


def _local_components():
    path = ROOT / "roles/bootstrap_generate_playbook_repo/files/local_components.py"
    spec = importlib.util.spec_from_file_location("local_components_sos", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_runner_never_auto_selects_day2_actions() -> None:
    lc = _local_components()
    for action in ("scale", "update", "access"):
        path = f"playbooks/shift_on_shift/ado-shift-on-shift-{action}-bootstrap.yml"
        assert lc.is_day2_helper(path)
        assert "Shift on Shift" in lc.day2_reason(path)
    for action in ("validate", "deploy", "status"):
        assert not lc.is_day2_helper(f"playbooks/shift_on_shift/ado-shift-on-shift-{action}-bootstrap.yml")
    assert "realm" in lc.day2_reason("playbooks/rhbk/ado-enable-realm-bootstrap.yml")


def test_overlay_does_not_copy_shift_on_shift_values(tmp_path: Path) -> None:
    env_dir = tmp_path / "group_vars/all/molecule"
    env_dir.mkdir(parents=True)
    generated = "---\nshift_on_shift_clusters:\n  - name: tenant-a\n"
    (env_dir / "vars_shift_on_shift.yml").write_text(generated, encoding="utf-8")
    (env_dir / "vault_shift_on_shift.yml").write_text("---\nshift_on_shift_pull_secrets: {}\n", encoding="utf-8")
    preflight = {
        "environment": "molecule",
        "domain": "example.test",
        "components": ["openshift"],
        "component_apps": {"openshift": ["shift_on_shift"]},
        "component_config": {
            "shift_on_shift": {
                "clusters": [{
                    "name": "tenant-a",
                    "namespace": "clusters",
                    "pull_secret_source": "vault",
                    "pull_secret": '{"auths": {"quay.io": {"auth": "U0VDUkVU"}}}',
                }],
                "pull_secret_token": "should-not-be-copied",
            }
        },
    }
    preflight_file = tmp_path / "preflight.json"
    preflight_file.write_text(json.dumps(preflight), encoding="utf-8")
    env = dict(
        os.environ,
        ADO_PREFLIGHT_JSON=str(preflight_file),
        ADO_ENV_DIR=str(env_dir),
        ADO_SELECTED_COMPONENTS=json.dumps(["shift_on_shift"]),
    )
    subprocess.run([sys.executable, str(OVERLAY)], env=env, cwd=tmp_path, check=True, capture_output=True)
    assert (env_dir / "vars_shift_on_shift.yml").read_text(encoding="utf-8") == generated
    for path in env_dir.iterdir():
        assert "U0VDUkVU" not in path.read_text(encoding="utf-8"), path.name
        assert "should-not-be-copied" not in path.read_text(encoding="utf-8"), path.name
