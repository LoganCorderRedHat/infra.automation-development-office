# ocp_hcp_kubevirt

Live end-to-end scenario for Shift on Shift. It creates a real hosted cluster
(two KubeVirt worker VMs, SingleReplica control plane), checks idempotence,
verifies readiness, scales the node pool 2 -> 3 -> 2, and deletes everything.

Excluded from PR CI (``ocp_*`` in ``pr_exclude.txt``). Run it only against a
management cluster that passes ``ocp_hcp_kubevirt_prereqs`` (OpenShift 4.20 to
4.22 with multicluster engine Operator 2.17 for a 4.22 hosted cluster, bare
metal, OpenShift Virtualization, MetalLB, a default StorageClass).

```bash
export K8S_AUTH_HOST=https://api.<management-cluster>:6443
export K8S_AUTH_API_KEY=<token with the permissions in docs/SHIFT_ON_SHIFT.md>
export K8S_AUTH_VERIFY_SSL=true
export SOS_RELEASE_IMAGE=quay.io/openshift-release-dev/ocp-release:4.22.0-multi
# Optional:
export SOS_CLUSTER_NAME=ado-molecule SOS_NAMESPACE=ado-molecule-hcp
export SOS_ROOT_VOLUME_STORAGE_CLASS=<RWX block class> SOS_ETCD_STORAGE_CLASS=<LVM class>
export SOS_ALLOW_WILDCARD_PATCH=false   # true lets the run enable wildcard routes

ansible-galaxy collection install . --force --no-deps -p ~/.ansible/collections
cd extensions/molecule && ln -sfn . molecule
molecule test -s ocp_hcp_kubevirt
```

Expect 25 to 40 minutes. The idempotence step must report no changes: the
second deploy finds the HostedCluster and does not re-apply it.
