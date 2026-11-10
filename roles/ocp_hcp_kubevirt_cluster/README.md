# Role: infra.automation_development_office.ocp_hcp_kubevirt_cluster

Deploy, inspect, scale, update, access, and delete hosted clusters on the
HyperShift KubeVirt platform (Shift on Shift): `HostedCluster` and `NodePool`
resources on an existing OpenShift management cluster, with KubeVirt virtual
machines as worker nodes.

## Role Author

Automation Development Office

## ✅ Role Requirements

- `kubernetes.core` (`k8s`, `k8s_info`, `k8s_json_patch`) and the Python `kubernetes` client
- Management cluster API access through `K8S_AUTH_*` or a kubeconfig
- Prerequisites from `ocp_hcp_kubevirt_prereqs` (checked automatically before deploy)
- The `hcp` CLI is not needed; the role uses the `hypershift.openshift.io/v1beta1` API

## 📦 Role Variables

| Variable | Description |
|----------|-------------|
| `ocp_hcp_kubevirt_cluster_action` | `deploy` (default), `status`, `scale`, `update`, `access`, or `delete` |
| `ocp_hcp_kubevirt_cluster_clusters` | Hosted cluster definitions (keys below) |
| `ocp_hcp_kubevirt_cluster_cluster_defaults` | Values merged under every definition |
| `ocp_hcp_kubevirt_cluster_name` | Target cluster; empty means all for `deploy`/`status`; required for the other actions |
| `ocp_hcp_kubevirt_cluster_pull_secrets` | Pull secret JSON per cluster for `pull_secret_source: vault` (vault only) |
| `ocp_hcp_kubevirt_cluster_validate` | Run the prerequisite check before deploy (default `true`) |
| `ocp_hcp_kubevirt_cluster_install_prerequisites` | `deploy`: install missing prerequisites first (MCE with HyperShift, OpenShift Virtualization, MetalLB, wildcard routes); existing installations are reused (default `false`; Preflight sets `true`) |
| `ocp_hcp_kubevirt_cluster_metallb_address_pools` | MetalLB address ranges, used only when MetalLB is not set up (default `[]`) |
| `ocp_hcp_kubevirt_cluster_manage_wildcard_route_admission` | Allow wildcard routes on the default IngressController; implied by install_prerequisites (default `false`) |
| `ocp_hcp_kubevirt_cluster_wait` | Wait for readiness (default `true`) |
| `ocp_hcp_kubevirt_cluster_hc_timeout_minutes` | Control plane Available timeout (default `30`) |
| `ocp_hcp_kubevirt_cluster_nodepool_timeout_minutes` | Worker VM join timeout (default `45`) |
| `ocp_hcp_kubevirt_cluster_version_timeout_minutes` | Hosted version rollout timeout (default `45`) |
| `ocp_hcp_kubevirt_cluster_verify_hosted_api` | Also query nodes and cluster operators through the hosted API (default `true`, non-fatal) |
| `ocp_hcp_kubevirt_cluster_render_only` | Write manifests to `ocp_hcp_kubevirt_cluster_render_dir` instead of applying |
| `ocp_hcp_kubevirt_cluster_replicas` | `scale`: new replica count |
| `ocp_hcp_kubevirt_cluster_autoscaling_min` | `scale`: autoscaling minimum (1 or more) |
| `ocp_hcp_kubevirt_cluster_autoscaling_max` | `scale`: autoscaling maximum |
| `ocp_hcp_kubevirt_cluster_target_release_image` | `update`: control plane release image |
| `ocp_hcp_kubevirt_cluster_update_nodepools` | `update`: update node pool releases after the control plane |
| `ocp_hcp_kubevirt_cluster_confirm_update` | `update`: must be `true` for any release change |
| `ocp_hcp_kubevirt_cluster_force_upgrade` | `update`: add the documented `force-upgrade-to` annotation (default `false`) |
| `ocp_hcp_kubevirt_cluster_channel` | `update`: set `spec.channel` (for example `stable-4.22`) |
| `ocp_hcp_kubevirt_cluster_kubeconfig_dest` | `access`: optional local path for the admin kubeconfig (mode `0600`) |
| `ocp_hcp_kubevirt_cluster_confirm_delete` | `delete`: must equal the hosted cluster name |
| `ocp_hcp_kubevirt_cluster_delete_namespace` | `delete`: also delete the namespace when ADO created it and it is empty |

Definition keys (defaults in parentheses): `name`, `namespace` (`clusters`),
`release_image`, `hosted_version` (required for digest images),
`pull_secret_source` (`management_cluster`, `vault`, `existing_secret`),
`pull_secret_name`, `ssh_public_key`, `base_domain` (empty uses the default
ingress under the management apps domain), `controller_availability_policy`
(`HighlyAvailable`), `api_publishing` (`LoadBalancer` or `NodePort` with
`api_server_address`), `cluster_network_cidr` (`10.132.0.0/14`),
`service_network_cidr` (`172.31.0.0/16`), `machine_network_cidr`,
`etcd_storage_class`, `etcd_storage_size` (`8Gi`), `nodepool_name`,
`worker_count` (`2`), `autoscaling_min`/`autoscaling_max`, `worker_cores`
(`2`), `worker_memory` (`8Gi`), `root_volume_size` (`32Gi`),
`root_volume_storage_class`, `root_volume_access_mode`,
`root_volume_volume_mode`, `root_volume_cache_strategy` (`None`),
`network_multiqueue` (`Enable`), `qos_class` (`Burstable`),
`vm_node_selector`, `additional_networks`, `attach_default_network` (`true`),
`node_upgrade_type` (`Replace`), `auto_repair`, `storage_class_mappings`,
`volume_snapshot_class_mappings`, `capabilities_enabled`,
`capabilities_disabled`, `channel`, `fips`, `require_live_migration`,
`create_apps_load_balancer` (`true` with a base domain), and `disconnected`
(`enabled`, `image_content_sources`, `additional_trust_bundle`,
`olm_catalog_placement`, `disable_default_sources`, `olm_catalog_images`,
`olm_registry_overrides`).

Results are in `ocp_hcp_kubevirt_cluster_results` (non-secret) and published
with `set_stats` as `shift_on_shift_results`.

## 🚀 Role Usage

```yaml
- name: Deploy a Shift on Shift hosted cluster
  hosts: localhost
  gather_facts: false
  tasks:
    - name: Deploy
      ansible.builtin.include_role:
        name: infra.automation_development_office.ocp_hcp_kubevirt_cluster
      vars:
        ocp_hcp_kubevirt_cluster_action: deploy
        ocp_hcp_kubevirt_cluster_clusters:
          - name: tenant-a
            namespace: clusters
            release_image: quay.io/openshift-release-dev/ocp-release:4.22.0-multi
            worker_count: 3
            worker_cores: 4
            worker_memory: 16Gi
            root_volume_size: 64Gi
            root_volume_storage_class: ocs-storagecluster-ceph-rbd-virtualization
            etcd_storage_class: lvms-vg1
            require_live_migration: true

    - name: Scale tenant-a to five workers
      ansible.builtin.include_role:
        name: infra.automation_development_office.ocp_hcp_kubevirt_cluster
      vars:
        ocp_hcp_kubevirt_cluster_action: scale
        ocp_hcp_kubevirt_cluster_name: tenant-a
        ocp_hcp_kubevirt_cluster_replicas: 5
        ocp_hcp_kubevirt_cluster_clusters: "{{ my_clusters }}"
```

## 🧪 Role Molecule Testing

- `extensions/molecule/integration_hcp_kubevirt_offline` (PR CI, no cluster): manifest
  rendering, input rejection, and the delete confirmation guard, with an idempotence pass.
- `extensions/molecule/integration_bootstrap_shift_on_shift` (PR CI, no cluster): generated
  seed playbooks, job templates, and the vars/vault split.
- `extensions/molecule/ocp_hcp_kubevirt` (live cluster, excluded from PR CI): deploy,
  idempotence, readiness, scale, delete.

```bash
ansible-galaxy collection install . --force --no-deps -p ~/.ansible/collections
cd extensions/molecule && ln -sfn . molecule
molecule test -s integration_hcp_kubevirt_offline
```

## 📁 Role Structure

```text
roles/ocp_hcp_kubevirt_cluster/
  README.md
  defaults/main.yml
  meta/main.yml
  vars/main.yml               # action lists
  tasks/main.yml              # dispatch per action and per cluster
  tasks/lookup.yml            # HostedCluster, NodePools, management apps domain
  tasks/deploy.yml            # create-if-absent, drift report, wait, verify
  tasks/create.yml            # namespace, secrets, trust bundle, HostedCluster, NodePool
  tasks/wait.yml              # control plane, node pool, version rollout
  tasks/apps_lb.yml           # custom base domain ingress load balancer
  tasks/verify.yml            # hosted API checks (non-fatal)
  tasks/hosted_kubeconfig.yml # in-memory admin kubeconfig (no_log)
  tasks/hosted_api_auth.yml   # pinned hosted API connection (overrides K8S_AUTH_*)
  tasks/hosted_api_cleanup.yml
  tasks/status.yml
  tasks/scale.yml
  tasks/update.yml
  tasks/access.yml
  tasks/delete.yml
  tasks/render.yml
  tasks/install_prerequisites.yml # install_prerequisites: MCE, Virtualization, MetalLB
  tasks/wildcard_routes.yml   # opt-in or install_prerequisites
```
