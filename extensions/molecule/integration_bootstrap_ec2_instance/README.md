# integration_bootstrap_ec2_instance

Verifies AWS-platform bootstrap generation for the ``ec2_instance`` app:

- seed playbooks under ``playbooks/aws/ec2/`` that
  ``import_playbook`` collection FQCNs
- Contoller job templates
- ``vars_ec2_instance.yml`` + shared ``vault_aws.yml`` (no per-app vault)
