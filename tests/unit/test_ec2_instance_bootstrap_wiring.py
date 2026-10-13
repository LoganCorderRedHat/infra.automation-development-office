"""EC2 instance bootstrap lives under the aws umbrella."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULTS = (
    ROOT
    / "roles"
    / "bootstrap_generate_playbook_repo"
    / "defaults"
    / "main.yml"
)
CREATE_SEED = (
    ROOT
    / "roles"
    / "bootstrap_generate_playbook_repo"
    / "files"
    / "playbooks"
    / "aws"
    / "ec2"
    / "ado-ec2-instance-create-bootstrap.yml"
)


def test_component_map_homes_ec2_instance_under_aws():
    data = yaml.safe_load(DEFAULTS.read_text())
    component_map = data["bootstrap_generate_playbook_repo_component_map"]
    assert "ec2_instance" in component_map["aws"]
    assert component_map["ec2_instance"] == ["ec2_instance"]
    assert "ec2_ami_copy" in component_map["aws"]


def test_create_bootstrap_imports_collection_fqcn():
    text = CREATE_SEED.read_text()
    assert "ansible.builtin.import_playbook: infra.ado.aws.ec2.ado-ec2-instance-create" in text


def test_generated_playbooks_include_ec2_instance_seeds():
    data = yaml.safe_load(DEFAULTS.read_text())
    apps = {
        item["app"]
        for item in data["bootstrap_generate_playbook_repo_generated_playbooks"]
        if item.get("app") == "ec2_instance"
    }
    assert apps == {"ec2_instance"}
    dests = {
        item["dest"]
        for item in data["bootstrap_generate_playbook_repo_generated_playbooks"]
        if item.get("app") == "ec2_instance"
    }
    assert "playbooks/aws/ec2/ado-ec2-instance-create-bootstrap.yml" in dests
    assert "playbooks/aws/ec2/ado-ec2-instance-delete-bootstrap.yml" in dests
    assert "playbooks/aws/ec2/ado-ec2-instance-modify-bootstrap.yml" in dests
    assert "playbooks/aws/ec2/ado-ec2-instance-info-bootstrap.yml" in dests
