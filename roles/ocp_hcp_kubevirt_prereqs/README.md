# Role: infra.automation_development_office.ocp_hcp_kubevirt_prereqs

Read-only prerequisite validation for hosted control planes (HyperShift) on
OpenShift Virtualization (Shift on Shift), based on the OpenShift 4.22
"Hosted control planes" documentation for the KubeVirt platform.

## Role Author

Automation Development Office

## ✅ Role Requirements

- `kubernetes.core` and the Python `kubernetes` client in the execution environment
- Management cluster API access through `K8S_AUTH_*` environment variables or a kubeconfig
- Read access to the resources listed in `docs/SHIFT_ON_SHIFT.md` (cluster version,
  nodes, pods, storage, MCE, HyperShift, OpenShift Virtualization, MetalLB, ingress)

The role never creates or changes cluster resources. The only write calls are
`SelfSubjectAccessReview` requests, which the API server evaluates and does not store.

## 📦 Role Variables

| Variable | Description |
|----------|-------------|
| `ocp_hcp_kubevirt_prereqs_clusters` | Hosted cluster definitions to check (same keys as `ocp_hcp_kubevirt_cluster_clusters`) |
| `ocp_hcp_kubevirt_prereqs_cluster_defaults` | Values merged under every definition |
| `ocp_hcp_kubevirt_prereqs_cluster_name` | Check only this hosted cluster (empty checks all) |
| `ocp_hcp_kubevirt_prereqs_pull_secrets` | Pull secret JSON per cluster name for `pull_secret_source: vault` (vault file only, never printed) |
| `ocp_hcp_kubevirt_prereqs_fail_on_missing` | Fail when a required prerequisite is missing (default `true`) |
| `ocp_hcp_kubevirt_prereqs_allow_unsupported_platform` | Lab override: report a non bare metal management cluster as an `UNSUPPORTED` warning (default `false`) |
| `ocp_hcp_kubevirt_prereqs_wildcard_remediation_planned` | Treat missing wildcard route admission as pending (set when the deploy run will enable it) |
| `ocp_hcp_kubevirt_prereqs_install_planned` | Items deploy installs when missing (`mce`, `virtualization`, `metallb`); reported as `planned` (WILL INSTALL) when their package is in a catalog source (default `[]`) |
| `ocp_hcp_kubevirt_prereqs_metallb_address_pools` | MetalLB address ranges deploy would configure (default `[]`) |
| `ocp_hcp_kubevirt_prereqs_load_balancer_check` | `metallb` (default) checks MetalLB for LoadBalancer publishing; `skip` trusts another load balancer |
| `ocp_hcp_kubevirt_prereqs_check_capacity` | Compare free worker CPU/memory with the requested control planes and worker VMs (default `true`) |
| `ocp_hcp_kubevirt_prereqs_check_permissions` | Run SelfSubjectAccessReviews for the deploy permissions (default `true`) |
| `ocp_hcp_kubevirt_prereqs_min_workers` | Minimum Ready workers (default `3`, the HyperShift requirement) |
| `ocp_hcp_kubevirt_prereqs_sizing` | Control plane baseline per hosted cluster (`control_plane_cpu: "5"`, `control_plane_memory: 18Gi`) |
| `ocp_hcp_kubevirt_prereqs_report_path` | Optional path for a JSON copy of the report (no secrets) |
| `ocp_hcp_kubevirt_prereqs_support_matrix` | Support matrix override; empty uses the built-in OpenShift 4.22 matrix |
| `ocp_hcp_kubevirt_prereqs_facts` | Test seam: evaluate these facts instead of querying the API |

Outputs `ocp_hcp_kubevirt_prereqs_report` with `ready`, `checks`, `missing`
(required prerequisites that failed), `optimizations` (optional
recommendations), and `summary`. Checks cover: management cluster version and
health, platform, workers, zones, capacity, maxPods, OVN-Kubernetes, MTU and
multiqueue, MCE version and hypershift components, HyperShift Operator and
supported versions, local-cluster and hypershift-addon, OpenShift
Virtualization health and version, default storage class, etcd and root volume
classes, live migration (CDI StorageProfile RWX), kubevirt-csi mappings,
snapshot class, wildcard routes, MetalLB, permissions, pull secrets, name
uniqueness, FIPS, the 4.22 support matrix, and disconnected mirror settings.

## 🚀 Role Usage

```yaml
- name: Validate Shift on Shift prerequisites
  hosts: localhost
  gather_facts: false
  tasks:
    - name: Check the management cluster
      ansible.builtin.include_role:
        name: infra.automation_development_office.ocp_hcp_kubevirt_prereqs
      vars:
        ocp_hcp_kubevirt_prereqs_clusters:
          - name: tenant-a
            namespace: clusters
            release_image: quay.io/openshift-release-dev/ocp-release:4.22.0-multi
            root_volume_storage_class: ocs-storagecluster-ceph-rbd-virtualization
            etcd_storage_class: lvms-vg1
            require_live_migration: true
        ocp_hcp_kubevirt_prereqs_report_path: /tmp/shift-on-shift-report.json
```

## 🧪 Role Molecule Testing

- `extensions/molecule/integration_hcp_kubevirt_offline` (runs in PR CI, no cluster): evaluates
  a ready and a not-ready fixture, checks every missing prerequisite is reported, and that
  `fail_on_missing` stops the play.
- `extensions/molecule/ocp_hcp_kubevirt` (live cluster, excluded from PR CI): runs as part of deploy.

```bash
ansible-galaxy collection install . --force --no-deps -p ~/.ansible/collections
cd extensions/molecule && ln -sfn . molecule
molecule test -s integration_hcp_kubevirt_offline
```

Unit tests for the evaluation logic: `tests/unit/plugins/filter/test_hcp_kubevirt.py`.

## 📁 Role Structure

```text
roles/ocp_hcp_kubevirt_prereqs/
  README.md
  defaults/main.yml
  meta/main.yml
  tasks/main.yml           # normalize, gather or use supplied facts, evaluate, report
  tasks/gather.yml         # read-only k8s_info calls
  tasks/pull_secrets.yml   # pull secret validity (no_log)
  tasks/access.yml         # SelfSubjectAccessReviews
  vars/main.yml            # CRDs probed before optional queries
plugins/filter/hcp_kubevirt.py  # evaluation logic and the 4.22 support matrix
```
