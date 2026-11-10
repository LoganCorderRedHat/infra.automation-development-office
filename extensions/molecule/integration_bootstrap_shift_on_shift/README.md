# integration_bootstrap_shift_on_shift

Offline (no cluster). Verifies bootstrap generation for the ``shift_on_shift``
OpenShift app from a preflight fixture with two hosted clusters:

- seven seed playbooks under ``playbooks/shift_on_shift/`` that pass
  ``ansible-playbook --syntax-check``
- seven Controller job templates (validate, deploy, status, scale, update,
  access, delete)
- ``vars_shift_on_shift.yml`` holds the cluster definitions with no pull secret
  material, and the generic preflight overlay does not spill keys to top-level
  vars
- ``vault_shift_on_shift.yml`` holds only the ``pull_secret_source: vault``
  pull secret
- the local (no AAP) run plan recommends only validate, deploy, and status;
  scale, update, access, and delete must be chosen explicitly

Run:

```bash
ansible-galaxy collection install . --force --no-deps -p ~/.ansible/collections
cd extensions/molecule && ln -sfn . molecule
molecule test -s integration_bootstrap_shift_on_shift
```
