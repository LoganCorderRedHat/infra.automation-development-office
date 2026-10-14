# integration_bootstrap_s3_bucket_policy

Verifies AWS-platform bootstrap generation for the ``s3_bucket_policy`` app:

- seed playbooks under ``playbooks/aws/s3/`` that ``import_playbook`` collection
  FQCNs
- Contoller job templates for set / set-from-file / info
- seeded sample policy ``policies/allow_list_and_read.json``
- ``vars_s3_bucket_policy.yml`` + shared ``vault_aws.yml`` (no per-app vault)
