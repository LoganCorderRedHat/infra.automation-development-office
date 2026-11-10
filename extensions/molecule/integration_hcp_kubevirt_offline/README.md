# integration_hcp_kubevirt_offline

Offline (no cluster) coverage for the Shift on Shift roles:

- ``ocp_hcp_kubevirt_prereqs`` evaluates fixture facts
  (``ocp_hcp_kubevirt_prereqs_facts`` skips every API call):
  - ``fixtures/facts_ready.yml``: OpenShift 4.22 + MCE 2.17 bare metal cluster
    that meets every required prerequisite
  - ``fixtures/facts_not_ready.yml``: OpenShift 4.18 + MCE 2.10 on vSphere with
    missing OpenShift Virtualization, storage, MetalLB, wildcard routes,
    permissions, and a bad pull secret; every gap must be reported, and
    ``fail_on_missing`` must stop the play
- ``ocp_hcp_kubevirt_cluster`` rejects invalid definitions and an unconfirmed
  delete before any API call, and renders ``HostedCluster``/``NodePool``
  manifests (``render_only``) for a default-ingress cluster and a custom-domain
  disconnected cluster
- reports and manifests contain no pull secret material
- converge is idempotent

Live cluster coverage is in ``ocp_hcp_kubevirt`` (excluded from PR CI).

```bash
ansible-galaxy collection install . --force --no-deps -p ~/.ansible/collections
cd extensions/molecule && ln -sfn . molecule
molecule test -s integration_hcp_kubevirt_offline
```
