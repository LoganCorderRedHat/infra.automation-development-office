# Shift on Shift: hosted OpenShift clusters on OpenShift Virtualization

Shift on Shift deploys and manages multiple independent OpenShift clusters on
one existing OpenShift management cluster with hosted control planes
(HyperShift) and the **KubeVirt platform**:

- each hosted cluster's control plane runs as pods in
  `<namespace>-<name>` on the management cluster (HyperShift Operator from
  the multicluster engine Operator, MCE)
- each hosted cluster's worker nodes are KubeVirt virtual machines on the
  management cluster's OpenShift Virtualization
- every hosted cluster has its own API endpoint, control plane, worker nodes,
  and lifecycle

This is the supported `HostedCluster`/`NodePool` KubeVirt platform from the
OpenShift 4.22 "Hosted control planes" documentation. It is not nested
standalone OpenShift with control plane VMs, and it does not use the Agent
(bare metal worker) platform.

Technical reference: OpenShift Container Platform 4.22, *Hosted control
planes*: requirements and support matrix, "Deploying hosted control planes on
OpenShift Virtualization", "Managing hosted control planes on OpenShift
Virtualization", "Deploying hosted control planes on OpenShift Virtualization
in a disconnected environment", "Updating hosted control planes", and
"Destroying a hosted cluster on OpenShift Virtualization". Resource fields
follow the `hypershift.openshift.io/v1beta1` API (HyperShift release-4.22).

## Components

| Piece | Purpose |
|-------|---------|
| `roles/ocp_hcp_kubevirt_prereqs` | Read-only prerequisite validation |
| `roles/ocp_hcp_kubevirt_cluster` | Deploy, status, scale, update, access, delete |
| `plugins/filter/hcp_kubevirt.py` | Input validation, 4.22 support matrix, prerequisite evaluation, manifest rendering |
| `shift_on_shift` OpenShift app (Preflight UI) | Generates `vars_shift_on_shift.yml`, `vault_shift_on_shift.yml`, seven playbooks under `playbooks/shift_on_shift/`, and seven AAP job templates |

Generated job templates (`ADO | Shift on Shift | ...`):

| Job template | Playbook | Changes cluster state |
|--------------|----------|-----------------------|
| Validate prerequisites | `ado-shift-on-shift-validate-bootstrap.yml` | No |
| Deploy hosted clusters | `ado-shift-on-shift-deploy-bootstrap.yml` | Creates missing hosted clusters only |
| Hosted cluster status | `ado-shift-on-shift-status-bootstrap.yml` | No |
| Scale node pool | `ado-shift-on-shift-scale-bootstrap.yml` | NodePool replicas or autoscaling |
| Update hosted cluster | `ado-shift-on-shift-update-bootstrap.yml` | Channel, autoRepair, releases (confirmation required) |
| Access details | `ado-shift-on-shift-access-bootstrap.yml` | No |
| Delete hosted cluster | `ado-shift-on-shift-delete-bootstrap.yml` | Deletes one cluster (typed confirmation) |

Without AAP, the Preflight local runner recommends only validate, deploy, and
status. Scale, update, access, and delete run only when selected.

## Prerequisites

The validate job reports each item as **MISSING** (required, blocks deploy),
**OPTIONAL** (recommended optimization), or **INFO**.

Required (from the 4.22 docs):

- Management cluster: a supported OpenShift version, Available and not
  failing, healthy cluster operators, on-premise **bare metal**, not
  single-node, **at least three Ready workers**, **OVN-Kubernetes**.
- Multicluster engine Operator installed and Available, with the `hypershift`
  and `hypershift-local-hosting` components enabled; HyperShift Operator
  running in `hypershift`; `local-cluster` managed; `hypershift-addon`
  Available. ADO's ACM component (`ocp_acm`) installs ACM, which includes MCE.
- **Support matrix**: for a 4.22 hosted cluster you need MCE 2.17, which runs
  on management clusters 4.20, 4.21, or 4.22. MCE 2.17 hosts 4.20 to 4.22;
  MCE 2.11 hosts 4.19 to 4.21; MCE 2.10 hosts 4.18 to 4.20. The hosted minor
  must also be in the HyperShift `supported-versions` ConfigMap.
- OpenShift Virtualization 4.14 or later installed and healthy (ADO component
  `ocp_virtualization`).
- A **default StorageClass**. Named etcd and root volume classes must exist.
- **Default ingress** (no base domain): wildcard route admission on the
  management cluster's default IngressController. Select *Allow wildcard
  route admission* in Preflight to let the deploy job set it; nothing else
  is changed cluster-wide.
- **LoadBalancer** API publishing (default): MetalLB with an `IPAddressPool`
  and an advertisement. The `ocp_metallb_install` role can configure it; it is
  not a Preflight component. NodePort publishing does not need MetalLB.
- Permissions for the automation identity (see [RBAC](#least-privilege-rbac)).
- A valid pull secret for each hosted cluster.
- Unique hosted cluster name (not `clusters`, not an existing managed cluster),
  and a namespace that is not a managed cluster namespace.
- FIPS hosted clusters need a FIPS-enabled management cluster.
- Live migration requested: a ReadWriteMany root volume class (checked with the
  CDI `StorageProfile`).
- Disconnected: management cluster IDMS/ICSP mirrors for
  `quay.io/openshift-release-dev/ocp-release` and `ocp-v4.0-art-dev`.

Recommended (optional optimizations):

- MTU 9000 or greater; with a lower MTU, set `network_multiqueue: Disable`.
- `topology.kubernetes.io/zone` labels on three or more workers for highly
  available control planes; `maxPods` headroom (about 78 pods per control plane).
- Fast dedicated etcd storage (for example LVM Storage); ReadWriteMany Block
  root volumes so worker VMs live migrate during management cluster maintenance.
- A default VolumeSnapshotClass; digest-pinned release images, a trust bundle,
  mirror registry credentials, and a management cluster `additionalTrustedCA`
  for disconnected clusters.

### Set up missing prerequisites

With *Set up missing prerequisites* (Preflight default; role variable
`ocp_hcp_kubevirt_cluster_install_prerequisites: true`) the deploy job installs
what the management cluster is missing before it creates hosted clusters, and
reuses what is already there:

| Prerequisite | What deploy does when it is missing |
|---|---|
| multicluster engine Operator + HyperShift | `ocp_mce_install`: Subscription in `multicluster-engine` on the newest `stable-X.Y` channel the support matrix allows for the management and hosted versions, a MultiClusterEngine, then waits for the HyperShift Operator (hosted control planes is enabled by default in MCE). Skipped when ACM or an existing Subscription manages MCE. |
| OpenShift Virtualization | Subscription to `kubevirt-hyperconverged` (default channel) in `openshift-cnv`, then a HyperConverged (`ocp_virtualization_install`) |
| MetalLB (LoadBalancer API or custom base domain) | `ocp_metallb_install` with the *MetalLB address pool* you enter: MetalLB instance, IPAddressPool, and L2Advertisement named `shift-on-shift` |
| Wildcard route admission (default ingress) | Patches the default IngressController |

Channels and catalog sources come from each package's PackageManifest, so
mirrored catalogs work. **Validate prerequisites** lists these as `WILL
INSTALL` instead of failing. Deploy checks first and installs nothing when
something it cannot install is missing: storage (a default StorageClass),
workers, versions, permissions, or a MetalLB address pool when MetalLB is not
set up. After installing, deploy validates again with nothing pending. Turn
the setting off to only validate; then the wildcard route opt-in is the only
cluster-wide change.

## Configure in Preflight

1. Select **OpenShift** and the **Shift on Shift** app.
2. Set the management cluster connection on the OpenShift tab (API URL and
   token). It is stored in `infra_config_vars.yml` and the encrypted
   `vault_openshift.yml`, like every OpenShift app.
3. On the **Shift on Shift** tab add one or more hosted clusters: name,
   namespace, release image (and version for digest images), worker count,
   CPU, memory, root disk size and class, etcd class, networking and
   endpoint settings, pull secret source, optional disconnected settings.
4. Keep *Set up missing prerequisites* on and enter a *MetalLB address pool*
   (free IPs on the cluster network) unless MetalLB is already set up.
5. Review the summary on the tab, then run bootstrap. Pull secrets with
   source *vault* go only to `vault_shift_on_shift.yml`, which is encrypted.
6. Run **Validate prerequisites**, then **Deploy hosted clusters**: in AAP, or
   without AAP from **Run generated playbooks** in Preflight (both are
   preselected there).

## Variables

`vars_shift_on_shift.yml` (no secrets) holds `shift_on_shift_clusters` and
the run options; `vault_shift_on_shift.yml` holds `shift_on_shift_pull_secrets`
for clusters with `pull_secret_source: vault`. See
[`docs/shift_on_shift/vars_shift_on_shift.example.yml`](shift_on_shift/vars_shift_on_shift.example.yml)
for every key with comments. The same definitions work when calling the roles
directly (see the role READMEs).

Pull secret sources:

| Source | Behavior |
|--------|----------|
| `management_cluster` (default) | Copies `openshift-config/pull-secret` into `<name>-pull-secret` |
| `vault` | Uses the JSON from `vault_shift_on_shift.yml` |
| `existing_secret` | References `pull_secret_name` in the hosted cluster namespace (must exist) |

## Deploy

The deploy job, per hosted cluster:

1. Validates prerequisites (stops on any missing item).
2. Looks up the `HostedCluster`. If it exists, nothing is re-applied or
   recreated. Differences in immutable fields (platform, base domain mode,
   storage driver, availability policy, OLM placement, networks, etcd class,
   capabilities, FIPS) are reported and left as they are. An ADO-created
   cluster that lost its default NodePool (interrupted first run) gets it back.
3. If absent: creates the namespace (labeled as ADO-owned), the pull secret,
   the SSH key secret, a one-time etcd AES-CBC key (never rotated by reruns),
   the trust bundle ConfigMap, the `HostedCluster`, and the default `NodePool`.
4. Waits for the control plane (`Available`; stops early on
   `ValidReleaseImage`, `ValidConfiguration`, or `SupportedHostedCluster`
   False), the node pool, and, for the default ingress, the hosted version
   rollout (`Completed`).
5. Custom base domain: creates the `<name>-apps` LoadBalancer Service in the
   control plane namespace and prints the DNS records to create
   (`api.<name>.<base>` and `*.apps.<name>.<base>`). The cluster reports
   Partial until DNS resolves.
6. Optionally queries the hosted API for nodes and cluster operators.
7. Prints the API URL, console URL, and the names of the admin kubeconfig and
   kubeadmin password secrets. Results are published as `shift_on_shift_results`.

Reruns are safe: they resume waiting and never recreate a cluster.

Typical times: 10 to 15 minutes to a ready hosted cluster.

## Inspect

**Hosted cluster status** reports `HostedCluster` conditions, version and
rollout state, API URL, node pool replicas and conditions (including
`KubeVirtNodesLiveMigratable`), immutable drift, and hosted API health.

## Scale

**Scale node pool** with the cluster name and either a replica count (0 or
more) or autoscaling minimum (1 or more; scale from zero is AWS only) and
maximum. Switching between the two is handled with a JSON patch. The job
waits for the node pool to converge. Running **Deploy** again with a changed
`worker_count` does not change an existing node pool; use Scale.

## Update

**Update hosted cluster** follows the documented order: update the management
cluster, then MCE, then the hosted control plane, then node pools.

- Channel (`stable-4.22`) and node pool `autoRepair` change without
  confirmation.
- Control plane release: checked against the 4.22 support matrix for the
  running MCE, the HyperShift `supported-versions` list, no downgrade, and
  node pools that would fall more than three minors behind. Refused while an
  installation or earlier update is still rolling out. Needs
  *Confirm release update*. *Force upgrade annotation* adds
  `hypershift.openshift.io/force-upgrade-to` as in the documented procedure;
  leave it off unless required.
- Node pools: never newer than the last *completed* control plane version
  (patch level included) and at most three minors behind. Needs
  confirmation. With *Wait* off, run the node pool update after the control
  plane update completes.

## Access

**Access details** prints the API URL, console URL, and where the
credentials are: secret `<name>-admin-kubeconfig` (key `kubeconfig`) and
`<name>-kubeadmin-password` in the hosted cluster namespace, plus the
`oc extract` command. Secret contents are never printed. For direct CLI runs,
`ocp_hcp_kubevirt_cluster_kubeconfig_dest` writes the kubeconfig to a local
file with mode 0600.

## Remove

**Delete hosted cluster** needs the cluster name and the same name typed in the
confirmation field. It deletes the auto-imported managed cluster (only when it
was created by the hosted cluster import), deletes the `HostedCluster` and
waits (HyperShift removes node pools, VMs, and the control plane namespace),
then deletes only the supporting objects ADO created for that cluster. The
namespace is deleted only when selected, ADO created it, and no other hosted
clusters remain in it. Remove the definition from Preflight or
`vars_shift_on_shift.yml` after deletion.

## Disconnected environments

Per hosted cluster (`disconnected.enabled: true`):

- `image_content_sources`: source and mirrors written to
  `HostedCluster.spec.imageContentSources`.
- `additional_trust_bundle`: PEM bundle for the mirror registry CA, stored in
  ConfigMap `<name>-user-ca-bundle` and referenced by
  `spec.additionalTrustBundle`.
- `olm_catalog_placement` (`management` or `guest`), `disable_default_sources`,
  `olm_catalog_images` (the four documented catalog image annotations), and
  `olm_registry_overrides` (`hypershift.openshift.io/olm-catalogs-is-registry-overrides`).
- Use a digest-pinned release image and set `hosted_version`.

Management cluster side (not changed by Shift on Shift): apply the IDMS and
catalog sources from oc-mirror (mirror with `kubeVirtContainer: true`), add the
registry CA to `image.config.openshift.io/cluster`, and mirror MCE. With a 4.21
or later management cluster, also mirror
`quay.io/openshift-release-dev/ocp-release:4.20.10-multi` (documented known issue).

## Security

- No credentials in collection defaults, templates, or examples. Pull secrets
  come from the management cluster, the encrypted vault file, or an existing
  secret.
- Pull secret, kubeconfig, and etcd key handling runs with `no_log`. The hosted
  admin kubeconfig is held in memory only and dropped after use.
- Hosted cluster API calls pass host, context, token, TLS verification, and CA
  from the hosted kubeconfig as explicit module parameters. Those override the
  management cluster `K8S_AUTH_HOST`, `K8S_AUTH_API_KEY`, `K8S_AUTH_VERIFY_SSL`,
  and `K8S_AUTH_SSL_CA_CERT`, so the management token is never sent to a hosted
  API server. The hosted CA (public) is written to a temporary file for the
  call and removed afterwards. `K8S_AUTH_CERT_FILE`/`KEY_FILE` and
  `K8S_AUTH_USERNAME`/`PASSWORD` are not overridden; do not set them for these
  job templates.
- Supporting objects carry `app.kubernetes.io/managed-by:
  infra.automation_development_office`; delete removes only matching objects.
- No Technology Preview fields are exposed (GPU host devices, tolerations).
  External infrastructure clusters are not used. Worker architecture is amd64.

### Least-privilege RBAC

[`docs/shift_on_shift/rbac-example.yml`](shift_on_shift/rbac-example.yml) is a
starting point for a dedicated automation service account: cluster-scoped read
access for validation, write access limited to HyperShift resources, secrets,
config maps, and services, a `resourceNames`-scoped read of
`openshift-config/pull-secret`, and an optional binding for the wildcard route
opt-in. Review it against your policies before use.

## Testing

| Coverage | Where | Needs a cluster |
|----------|-------|-----------------|
| Input validation, support matrix, prerequisite evaluation, manifests, drift, upgrade and skew rules, status summaries | `tests/unit/plugins/filter/test_hcp_kubevirt.py` | No |
| Seeds, job templates, registry, run plan, overlay secret handling | `tests/unit/bootstrap/test_shift_on_shift_seed_wiring.py` | No |
| Roles against fixture facts, failure handling, rendering, delete guard, idempotence | Molecule `integration_hcp_kubevirt_offline` | No |
| Preflight JSON to generated repo, syntax of generated playbooks, vars/vault split | Molecule `integration_bootstrap_shift_on_shift` | No |
| Deploy, idempotence, readiness, scale, delete | Molecule `ocp_hcp_kubevirt` | Yes |

### End-to-end test against a cluster

Use a management cluster that passes the validate job (bare metal OpenShift
4.20 to 4.22 with MCE 2.17 for a 4.22 hosted cluster, OpenShift
Virtualization, MetalLB, default StorageClass):

1. Export `K8S_AUTH_HOST`, `K8S_AUTH_API_KEY`, `K8S_AUTH_VERIFY_SSL`, and
   `SOS_RELEASE_IMAGE`; optionally `SOS_ROOT_VOLUME_STORAGE_CLASS` and
   `SOS_ETCD_STORAGE_CLASS` (see `extensions/molecule/ocp_hcp_kubevirt/README.md`).
2. `molecule test -s ocp_hcp_kubevirt`.
3. Expected: validation passes; HostedCluster Available and version Completed;
   two worker nodes Ready; the idempotence step reports no changes; scaling to
   three workers and back converges; delete removes the HostedCluster, its VMs,
   the control plane namespace, and the test namespace.

Through ADO: run bootstrap with the Shift on Shift app, then the Validate,
Deploy, Status, Scale, Access, and Delete job templates in that order, and
check the same results.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Validate reports `matrix.hosted` or `release.supported_version` | MCE is too old for the release; update MCE (after the management cluster) or choose a supported release |
| Deploy stops with `ValidReleaseImage` False | Release image or pull secret; in disconnected mode the management IDMS mirrors |
| Control plane not Available | Pods in `<namespace>-<name>`, etcd PVCs bound, `oc get hostedcluster -n <namespace> <name> -o yaml` conditions |
| Node pool not converging | `oc get vm,vmi -n <namespace>-<name>`, VM events, storage capacity, `oc get nodepool -n <namespace>` conditions |
| Version stays Progressing with default ingress | Wildcard route admission on the management IngressController; console and ingress operators in the hosted cluster |
| Custom domain cluster stays Partial | DNS for `api.` and `*.apps.` records; `<name>-apps` Service external IP |
| `KubeVirtNodesLiveMigratable` False | Root volume and mapped classes are not ReadWriteMany |
| Hosted API verification "not reachable" | The hosted API load balancer address is not routable from the execution environment; management-side status still decides readiness |
| must-gather | `oc adm must-gather --image=registry.redhat.io/rhacm2/acm-must-gather-rhel9:v2.17 /usr/bin/gather hosted-cluster-namespace=<namespace> hosted-cluster-name=<name>` |

## Limitations

- KubeVirt platform only, with VMs on the management cluster (no external
  infrastructure cluster, no Agent bare metal workers).
- Shift on Shift creates one default node pool per hosted cluster. Node pools
  created another way can be scaled and updated by name (`nodepool_name`).
- Immutable fields are never changed in place; recreate the hosted cluster to
  change them.
- DNS records for custom base domains are not created.
- Without *Set up missing prerequisites*, operators are not installed; with
  it, an existing MCE is not upgraded to a newer channel, and storage is never
  installed.
