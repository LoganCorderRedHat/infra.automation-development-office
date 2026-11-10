# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the Shift on Shift (HyperShift KubeVirt) filter plugin."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]


def _load():
    path = ROOT / "plugins" / "filter" / "hcp_kubevirt.py"
    spec = importlib.util.spec_from_file_location("hcp_kubevirt_filter", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


F = _load()
RELEASE_422 = "quay.io/openshift-release-dev/ocp-release:4.22.0-multi"
DIGEST = "sha256:" + "a" * 64


def _cluster(**overrides):
    base = {"name": "tenant-a", "release_image": RELEASE_422}
    base.update(overrides)
    return F.normalize_cluster(base)


def _ready_facts():
    return {
        "crds": {k: True for k in (
            "hostedclusters", "nodepools", "mce", "hco", "kubevirt", "cdi", "storageprofiles",
            "managedclusters", "managedclusteraddons", "metallb", "volumesnapshotclasses",
        )},
        "clusterversion": {"version": "4.22.1", "available": True, "progressing": False, "failing": False},
        "clusteroperators": [{"name": "kube-apiserver", "available": True, "degraded": False}],
        "infrastructure": {"platform": "BareMetal", "control_plane_topology": "HighlyAvailable"},
        "network": {"type": "OVNKubernetes", "mtu": 9000},
        "nodes": [
            {"name": f"w{i}", "worker": True, "ready": True, "schedulable": True,
             "cpu_allocatable_m": 64000, "memory_allocatable_b": 256 * 1024 ** 3,
             "pods_allocatable": 500, "zone": z}
            for i, z in enumerate("abc")
        ],
        "pod_requests": {},
        "mce": {"present": True, "version": "2.17.0", "phase": "Available",
                "hypershift_enabled": None, "hypershift_local_hosting_enabled": None},
        "hypershift_operator": {"present": True, "available": True},
        "supported_versions": ["4.22", "4.21", "4.20"],
        "local_cluster": {"present": True},
        "managed_clusters": ["local-cluster"],
        "hypershift_addon": {"checked": True, "available": True},
        "existing_hostedclusters": [],
        "cnv": {"present": True, "version": "4.22.0", "available": True, "degraded": False},
        "storage_classes": [{"name": "rwx", "provisioner": "rbd.csi.example.test", "default": True},
                            {"name": "lvms", "provisioner": "topolvm.io", "default": False}],
        "storage_profiles": {"rwx": [{"access_modes": ["ReadWriteMany"], "volume_mode": "Block"}]},
        "volume_snapshot_classes": [{"name": "snap", "default": True}],
        "ingress": {"wildcard_policy": "WildcardsAllowed", "default_domain": "apps.mgmt.example.test"},
        "metallb": {"instance_present": True, "pools": 1, "advertisements": 1},
        "mirror_sources": [],
        "image_additional_trusted_ca": False,
        "fips_enabled": False,
        "pull_secrets": {"tenant-a": {"valid": True, "registries": ["quay.io"], "error": ""}},
        "access": {"create hostedclusters.hypershift.openshift.io in clusters": True},
    }


def _missing(report):
    return {c["id"] for c in report["missing"]}


# ---------------------------------------------------------------- versions


@pytest.mark.parametrize(
    "value,expected",
    [
        ("4.22.3", "4.22.3"),
        ("4.22", "4.22"),
        (RELEASE_422, "4.22.0"),
        ("quay.io/openshift-release-dev/ocp-release:4.21.10-x86_64", "4.21.10"),
        ("mirror.example:5000/ocp/release@" + DIGEST, ""),
        ("", ""),
        ("v4.20.1", "4.20.1"),
    ],
)
def test_parse_version(value, expected):
    assert F.parse_version(value) == expected


def test_version_compare_and_minor():
    assert F.version_compare("4.22.0", "4.21.9") == 1
    assert F.version_compare("4.22", "4.22.0") == 0
    assert F.version_compare("4.20.1", "4.20.2") == -1
    assert F.minor_version(RELEASE_422) == "4.22"


def test_quantities():
    assert F.quantity_to_bytes("8Gi") == 8 * 1024 ** 3
    assert F.quantity_to_bytes("500M") == 500 * 1000 ** 2
    assert F.quantity_to_bytes("bogus") is None
    assert F.cpu_to_millicores("2") == 2000
    assert F.cpu_to_millicores("250m") == 250


# ------------------------------------------------------- normalize/validate


def test_defaults_follow_api_and_docs():
    c = _cluster()
    assert c["namespace"] == "clusters"
    assert c["hcp_namespace"] == "clusters-tenant-a"
    assert c["hosted_version"] == "4.22.0"
    assert c["base_domain_passthrough"] is True
    assert c["controller_availability_policy"] == "HighlyAvailable"
    assert c["api_publishing"] == "LoadBalancer"
    assert c["networking"]["cluster_cidr"] == ["10.132.0.0/14"]
    assert c["networking"]["service_cidr"] == ["172.31.0.0/16"]
    assert c["etcd"]["size"] == "8Gi"
    pool = c["nodepool"]
    assert (pool["name"], pool["replicas"], pool["cores"], pool["memory"]) == ("tenant-a", 2, 2, "8Gi")
    assert pool["root_volume"]["size"] == "32Gi"
    assert (pool["multiqueue"], pool["qos_class"], pool["upgrade_type"]) == ("Enable", "Burstable", "Replace")
    assert c["pull_secret_name"] == "tenant-a-pull-secret"
    assert F.cluster_errors(c) == []


def test_live_migration_implies_rwx_block():
    c = _cluster(require_live_migration=True)
    assert c["nodepool"]["root_volume"]["access_mode"] == "ReadWriteMany"
    assert c["nodepool"]["root_volume"]["volume_mode"] == "Block"
    bad = _cluster(require_live_migration=True, root_volume_access_mode="ReadWriteOnce")
    assert any("require_live_migration" in e for e in F.cluster_errors(bad))


@pytest.mark.parametrize(
    "overrides,fragment",
    [
        ({"name": ""}, "name is required"),
        ({"name": "Tenant_A"}, "RFC 1123"),
        ({"name": "clusters", "namespace": "hosted"}, "must not be 'clusters'"),
        ({"namespace": "tenant-a"}, "namespace must differ"),
        ({"namespace": "openshift-foo"}, "is reserved"),
        ({"namespace": "x" * 40, "name": "y" * 30}, "exceeds 63"),
        ({"release_image": ""}, "release_image is required"),
        ({"release_image": "not an image"}, "not a valid image"),
        ({"release_image": "mirror.example:5000/ocp/release@" + DIGEST}, "hosted_version is required"),
        ({"pull_secret_source": "file"}, "pull_secret_source must be one of"),
        ({"pull_secret_source": "existing_secret"}, "pull_secret_name is required"),
        ({"api_publishing": "NodePort"}, "api_server_address is required"),
        ({"api_publishing": "Ingress"}, "api_publishing must be one of"),
        ({"cluster_network_cidr": "10.0.0.0/8", "service_network_cidr": "10.1.0.0/16"}, "overlaps"),
        ({"cluster_network_cidr": "not-a-cidr"}, "not a valid CIDR"),
        ({"worker_cores": 0}, "worker_cores"),
        ({"worker_memory": "lots"}, "worker_memory"),
        ({"worker_count": -1}, "worker_count"),
        ({"autoscaling_min": 0, "autoscaling_max": 3}, "scale from zero"),
        ({"autoscaling_min": 4, "autoscaling_max": 3}, "autoscaling_max"),
        ({"root_volume_access_mode": "ReadOnlyMany"}, "root_volume_access_mode"),
        ({"qos_class": "BestEffort"}, "qos_class"),
        ({"attach_default_network": False}, "attach_default_network"),
        ({"additional_networks": ["badformat"]}, "<namespace>/<name>"),
        ({"capabilities_disabled": ["Ingress"]}, "requires disabling Console"),
        ({"capabilities_disabled": ["Bogus"]}, "unknown capability"),
        ({"capabilities_enabled": ["baremetal"], "capabilities_disabled": ["baremetal"]}, "both enabled and disabled"),
        ({"channel": "latest"}, "stable-4.22"),
        ({"ssh_public_key": "not-a-key"}, "OpenSSH public key"),
        ({"disconnected": {"image_content_sources": [{"source": "quay.io/x"}]}}, "at least one mirror"),
        ({"disconnected": {"additional_trust_bundle": "hello"}}, "PEM"),
        ({"storage_class_mappings": ["onlyinfra"]}, "guest class"),
    ],
)
def test_cluster_errors(overrides, fragment):
    errors = F.cluster_errors(_cluster(**overrides))
    assert any(fragment in e for e in errors), errors


def test_capability_disable_needs_420_hosted():
    c = _cluster(release_image="quay.io/openshift-release-dev/ocp-release:4.19.5-multi",
                 capabilities_disabled=["Insights"])
    assert any("4.20 or later" in e for e in F.cluster_errors(c))
    ok = _cluster(release_image="quay.io/openshift-release-dev/ocp-release:4.19.5-multi",
                  capabilities_disabled=["ImageRegistry"])
    assert F.cluster_errors(ok) == []


def test_cluster_definitions_select_and_duplicates():
    out = F.cluster_definitions([{"name": "a", "release_image": RELEASE_422},
                                 {"name": "b", "release_image": RELEASE_422}], {}, "b")
    assert [c["name"] for c in out["clusters"]] == ["b"]
    assert out["errors"] == []
    dup = F.cluster_definitions([{"name": "a", "release_image": RELEASE_422}] * 2)
    assert any("duplicate" in e for e in dup["errors"])
    missing = F.cluster_definitions([{"name": "a", "release_image": RELEASE_422}], {}, "zzz")
    assert any("not defined" in e for e in missing["errors"])


def test_defaults_merge_under_cluster_values():
    out = F.cluster_definitions(
        [{"name": "a", "worker_cores": 8}],
        {"release_image": RELEASE_422, "worker_cores": 4, "disconnected": {"olm_catalog_placement": "guest"}},
    )
    c = out["clusters"][0]
    assert c["nodepool"]["cores"] == 8
    assert c["release_image"] == RELEASE_422
    assert c["disconnected"]["olm_catalog_placement"] == "guest"


def test_string_forms_are_accepted():
    c = _cluster(vm_node_selector="role=virt,size=large", additional_networks="ns1/nad1, ns2/nad2",
                 storage_class_mappings=["infra-rwx/guest-block,group=g1"])
    assert c["nodepool"]["node_selector"] == {"role": "virt", "size": "large"}
    assert c["nodepool"]["additional_networks"] == ["ns1/nad1", "ns2/nad2"]
    assert c["storage_class_mappings"] == [{"infra": "infra-rwx", "guest": "guest-block", "group": "g1"}]


# ---------------------------------------------------------------- manifests


def test_hostedcluster_matches_hcp_cli_render_for_default_ingress():
    hc = F.hostedcluster_manifest(_cluster())
    spec = hc["spec"]
    assert hc["apiVersion"] == "hypershift.openshift.io/v1beta1"
    assert spec["platform"] == {"type": "KubeVirt", "kubevirt": {"baseDomainPassthrough": True}}
    assert spec["dns"] == {"baseDomain": ""}
    assert spec["services"] == [
        {"service": "APIServer", "servicePublishingStrategy": {"type": "LoadBalancer"}},
        {"service": "Ignition", "servicePublishingStrategy": {"type": "Route"}},
        {"service": "Konnectivity", "servicePublishingStrategy": {"type": "Route"}},
        {"service": "OAuthServer", "servicePublishingStrategy": {"type": "Route"}},
    ]
    assert spec["secretEncryption"] == {"type": "aescbc", "aescbc": {"activeKey": {"name": "tenant-a-etcd-encryption-key"}}}
    assert spec["etcd"]["managed"]["storage"] == {"type": "PersistentVolume", "persistentVolume": {"size": "8Gi"}}
    assert spec["sshKey"] == {}
    assert spec["olmCatalogPlacement"] == "management"
    assert "infraID" not in spec  # generated by the HyperShift Operator
    assert hc["metadata"]["labels"]["app.kubernetes.io/managed-by"] == "infra.automation_development_office"


def test_hostedcluster_nodeport_custom_domain_and_disconnected():
    c = _cluster(
        base_domain="Tenants.Example.Test", api_publishing="NodePort", api_server_address="192.0.2.10",
        etcd_storage_class="lvms", ssh_public_key="ssh-ed25519 AAAAC3Nz test",
        storage_class_mappings=[{"infra_storage_class": "rwx", "guest_storage_class": "guest"}],
        volume_snapshot_class_mappings=[{"infra_volume_snapshot_class": "snap", "guest_volume_snapshot_class": "gsnap"}],
        capabilities_disabled=["ImageRegistry"], channel="stable-4.22", machine_network_cidr="192.0.2.0/24",
        disconnected={
            "enabled": True,
            "image_content_sources": [{"source": "quay.io/openshift-release-dev/ocp-release", "mirrors": "m.example/rel"}],
            "additional_trust_bundle": "-----BEGIN CERTIFICATE-----\nX\n-----END CERTIFICATE-----\n",
            "olm_catalog_placement": "guest", "disable_default_sources": True,
            "olm_catalog_images": {"redhat_operators": "m.example/redhat/redhat-operator-index:v4.22"},
        },
    )
    assert F.cluster_errors(c) == []
    hc = F.hostedcluster_manifest(c)
    spec = hc["spec"]
    assert spec["dns"]["baseDomain"] == "tenants.example.test"
    assert "baseDomainPassthrough" not in spec["platform"]["kubevirt"]
    assert {s["service"] for s in spec["services"]} == {"APIServer", "OAuthServer", "OIDC", "Konnectivity", "Ignition"}
    assert all(s["servicePublishingStrategy"] == {"type": "NodePort", "nodePort": {"address": "192.0.2.10"}} for s in spec["services"])
    assert spec["etcd"]["managed"]["storage"]["persistentVolume"]["storageClassName"] == "lvms"
    assert spec["sshKey"] == {"name": "tenant-a-ssh-key"}
    driver = spec["platform"]["kubevirt"]["storageDriver"]
    assert driver["type"] == "Manual"
    assert driver["manual"]["storageClassMapping"] == [{"infraStorageClassName": "rwx", "guestStorageClassName": "guest"}]
    assert driver["manual"]["volumeSnapshotClassMapping"] == [{"infraVolumeSnapshotClassName": "snap", "guestVolumeSnapshotClassName": "gsnap"}]
    assert spec["imageContentSources"] == [{"source": "quay.io/openshift-release-dev/ocp-release", "mirrors": ["m.example/rel"]}]
    assert spec["additionalTrustBundle"] == {"name": "tenant-a-user-ca-bundle"}
    assert spec["olmCatalogPlacement"] == "guest"
    assert spec["configuration"] == {"operatorhub": {"disableAllDefaultSources": True}}
    assert spec["capabilities"] == {"disabled": ["ImageRegistry"]}
    assert spec["channel"] == "stable-4.22"
    assert spec["networking"]["machineNetwork"] == [{"cidr": "192.0.2.0/24"}]
    assert hc["metadata"]["annotations"] == {
        "hypershift.openshift.io/redhat-operators-catalog-image": "m.example/redhat/redhat-operator-index:v4.22"
    }


def test_nodepool_replicas_and_autoscaling():
    np = F.nodepool_manifest(_cluster(worker_count=3, worker_cores=4, worker_memory="16Gi",
                                      root_volume_storage_class="rwx", require_live_migration=True,
                                      vm_node_selector={"role": "virt"}, root_volume_cache_strategy="PVC"))
    spec = np["spec"]
    assert spec["replicas"] == 3 and "autoScaling" not in spec
    kv = spec["platform"]["kubevirt"]
    assert kv["compute"] == {"cores": 4, "memory": "16Gi", "qosClass": "Burstable"}
    assert kv["rootVolume"] == {
        "type": "Persistent",
        "persistent": {"size": "32Gi", "storageClass": "rwx", "accessModes": ["ReadWriteMany"], "volumeMode": "Block"},
        "cacheStrategy": {"type": "PVC"},
    }
    assert kv["nodeSelector"] == {"role": "virt"}
    assert spec["management"] == {"upgradeType": "Replace", "autoRepair": False}
    assert spec["arch"] == "amd64"
    auto = F.nodepool_manifest(_cluster(autoscaling_min=2, autoscaling_max=5))["spec"]
    assert auto["autoScaling"] == {"min": 2, "max": 5} and "replicas" not in auto


def test_supporting_objects_and_existing_pull_secret():
    objs = F.supporting_objects(_cluster(base_domain="example.test"))
    assert objs["pull_secret"] == "tenant-a-pull-secret"
    assert objs["secret_labels"]["hypershift.openshift.io/safe-to-delete-with-cluster"] == "true"
    assert objs["apps_service"] == "tenant-a-apps"
    existing = _cluster(pull_secret_source="existing_secret", pull_secret_name="corp-pull")
    assert F.hostedcluster_manifest(existing)["spec"]["pullSecret"] == {"name": "corp-pull"}
    assert F.supporting_objects(existing)["pull_secret"] == ""


def test_pull_secret_check_never_returns_content():
    good = F.pull_secret_check(json.dumps({"auths": {"quay.io": {"auth": "c2VjcmV0"}}}))
    assert good == {"valid": True, "registries": ["quay.io"], "error": ""}
    assert "c2VjcmV0" not in json.dumps(good)
    assert F.pull_secret_check("")["valid"] is False
    assert F.pull_secret_check("{not json")["error"] == "pull secret is not valid JSON"
    assert F.pull_secret_check('{"auths": {}}')["valid"] is False


# ----------------------------------------------------------- support matrix


@pytest.mark.parametrize(
    "mgmt,mce,hosted,ok",
    [
        ("4.22.1", "2.17.0", "4.22.0", True),
        ("4.20.5", "2.17.2", "4.22.0", True),
        ("4.22.1", "2.17.0", "4.19.0", False),  # 2.17 hosts 4.20-4.22
        ("4.18.20", "2.10.1", "4.22.0", False),  # 4.22 needs MCE 2.17
        ("4.18.20", "2.10.1", "4.20.3", True),
        ("4.19.1", "2.17.0", "4.21.0", False),  # 2.17 runs on 4.20-4.22 management clusters
        ("4.22.1", "2.12.0", "4.22.0", False),  # unknown MCE release
        ("4.17.3", "2.8.0", "4.16.1", False),  # 4.17 is not a KubeVirt platform version
    ],
)
def test_support_check(mgmt, mce, hosted, ok):
    assert F.support_check(mgmt, mce, hosted)["ok"] is ok


def test_support_matrix_matches_422_docs():
    m = F.SUPPORT_MATRIX
    assert m["mce"]["2.17"] == {"management": ["4.20", "4.21", "4.22"], "hosted": ["4.20", "4.21", "4.22"]}
    assert m["mce"]["2.11"]["management"] == ["4.19", "4.20", "4.21"]
    assert m["mce"]["2.10"]["hosted"] == ["4.18", "4.19", "4.20"]
    assert "4.17" not in m["kubevirt_platform"]["management"]
    assert m["kubevirt_platform"]["hosted"][-1] == "4.22"


def test_support_check_accepts_override():
    custom = {"mce": {"2.99": {"management": ["4.22"], "hosted": ["4.23"]}}}
    assert F.support_check("4.22.0", "2.99.1", "4.23.0", custom)["ok"] is True


# ------------------------------------------------------------ prereq report


def test_ready_cluster_has_no_missing_prerequisites():
    report = F.prereq_report(_ready_facts(), [_cluster(etcd_storage_class="lvms", require_live_migration=True)])
    assert report["ready"] is True, [c["message"] for c in report["missing"]]
    ids = {c["id"]: c["status"] for c in report["checks"]}
    assert ids["storage.live_migration"] == "pass"
    assert ids["storage.etcd_low_latency"] == "pass"
    assert ids["matrix.hosted"] == "pass"


@pytest.mark.parametrize(
    "mutate,expected",
    [
        (lambda f: f["infrastructure"].update(platform="AWS"), "management.platform"),
        (lambda f: f["infrastructure"].update(control_plane_topology="SingleReplica"), "management.not_sno"),
        (lambda f: f.update(nodes=f["nodes"][:2]), "management.workers"),
        (lambda f: f["clusterversion"].update(failing=True), "management.available"),
        (lambda f: f.update(clusteroperators=[{"name": "etcd", "available": True, "degraded": True}]), "management.cluster_operators"),
        (lambda f: f["network"].update(type="OpenShiftSDN"), "network.ovn"),
        (lambda f: f.update(mce={"present": False}), "mce.installed"),
        (lambda f: f["mce"].update(hypershift_enabled=False), "mce.hypershift_enabled"),
        (lambda f: f["hypershift_operator"].update(available=False), "hypershift.operator"),
        (lambda f: f["local_cluster"].update(present=False), "mce.local_cluster"),
        (lambda f: f["hypershift_addon"].update(available=False), "mce.hypershift_addon"),
        (lambda f: f.update(cnv={"present": False}), "virt.installed"),
        (lambda f: f["cnv"].update(degraded=True), "virt.healthy"),
        (lambda f: f["cnv"].update(version="4.13.9"), "virt.version"),
        (lambda f: f.update(storage_classes=[]), "storage.default_class"),
        (lambda f: f["ingress"].update(wildcard_policy="WildcardsDisallowed"), "ingress.wildcard_routes"),
        (lambda f: f.update(metallb={"instance_present": False, "pools": 0, "advertisements": 0}), "ingress.load_balancer"),
        (lambda f: f["access"].update({"create secrets in clusters": False}), "access.permissions"),
        (lambda f: f["pull_secrets"].update({"tenant-a": {"valid": False, "error": "empty"}}), "pull_secret.valid"),
        (lambda f: f.update(supported_versions=["4.21", "4.20"]), "release.supported_version"),
        (lambda f: f["mce"].update(version="2.11.0"), "matrix.hosted"),
        (lambda f: f.update(managed_clusters=["local-cluster", "tenant-a"]), "cluster.unique_name"),
        # 3 x 2 vCPU free < 5 vCPU control plane + 2 workers x 2 cores
        (lambda f: f.update(nodes=[dict(n, cpu_allocatable_m=2000) for n in f["nodes"]]), "management.capacity"),
    ],
)
def test_each_missing_prerequisite_is_reported(mutate, expected):
    facts = copy.deepcopy(_ready_facts())
    mutate(facts)
    report = F.prereq_report(facts, [_cluster()])
    assert report["ready"] is False
    assert expected in _missing(report), sorted(_missing(report))


def test_optional_optimizations_do_not_block():
    facts = _ready_facts()
    facts["network"]["mtu"] = 1500
    facts["volume_snapshot_classes"] = []
    facts["clusterversion"]["progressing"] = True
    report = F.prereq_report(facts, [_cluster()])
    assert report["ready"] is True
    warns = {c["id"] for c in report["optimizations"]}
    assert {"network.mtu", "network.multiqueue", "storage.default_snapshot_class", "management.not_updating"} <= warns


def test_unsupported_platform_override_downgrades_to_warning():
    facts = _ready_facts()
    facts["infrastructure"]["platform"] = "VSphere"
    blocked = F.prereq_report(facts, [_cluster()])
    assert "management.platform" in _missing(blocked)
    allowed = F.prereq_report(facts, [_cluster()], {"allow_unsupported_platform": True})
    assert allowed["ready"] is True
    warning = [c for c in allowed["optimizations"] if c["id"] == "management.platform"][0]
    assert warning["message"].startswith("UNSUPPORTED")


def _package(name, channels, default="", source="redhat-operators"):
    return {
        "metadata": {"name": name},
        "status": {"catalogSource": source, "catalogSourceNamespace": "openshift-marketplace",
                   "defaultChannel": default or channels[-1], "channels": [{"name": c} for c in channels]},
    }


def _bare_facts():
    """Ready facts on a cluster without MCE, Virtualization, or MetalLB."""
    facts = _ready_facts()
    facts["mce"] = {"present": False}
    facts["hypershift_operator"] = {"present": False, "available": False}
    facts["supported_versions"] = []
    facts["hypershift_addon"] = {}
    facts["local_cluster"] = {}
    facts["cnv"] = {"present": False}
    facts["storage_profiles"] = {}
    facts["metallb"] = {"instance_present": False, "pools": 0, "advertisements": 0}
    for key in ("hostedclusters", "nodepools", "mce", "hco", "kubevirt", "cdi", "storageprofiles",
                "managedclusters", "managedclusteraddons", "metallb"):
        facts["crds"][key] = False
    facts["packages"] = {
        "mce": _package("multicluster-engine", ["stable-2.10", "stable-2.11", "stable-2.17"]),
        "virtualization": _package("kubevirt-hyperconverged", ["stable"]),
        "metallb": _package("metallb-operator", ["stable"]),
    }
    return facts


def test_mce_channel_follows_the_support_matrix():
    pkg = F.package_facts(_package("multicluster-engine", ["stable-2.10", "stable-2.11", "stable-2.17"]))
    assert F.mce_channel(pkg, "4.22.1", ["4.22.0"])["channel"] == "stable-2.17"
    assert F.mce_channel(pkg, "4.20.3", ["4.20.1"])["channel"] == "stable-2.17"
    assert F.mce_channel(pkg, "4.19.2", ["4.19.0"])["channel"] == "stable-2.11"
    assert F.mce_channel(pkg, "4.18.9", ["4.18.0"])["channel"] == "stable-2.10"
    blocked = F.mce_channel(pkg, "4.18.9", ["4.22.0"])
    assert blocked["ok"] is False and "no multicluster-engine channel" in blocked["message"]
    assert F.mce_channel({}, "4.22.1", ["4.22.0"])["ok"] is False


def test_package_choice_spans_every_catalog_source():
    snapshot = _package("multicluster-engine", ["stable-2.9", "stable-2.10", "stable-2.11"], source="redhat-operators-snapshot-lightspeed")
    live = _package("multicluster-engine", ["stable-2.9", "stable-2.10", "stable-2.11", "stable-2.17"])
    # The snapshot catalog stops at 2.11; 4.22 hosted needs 2.17 from redhat-operators.
    plan = F.mce_channel([snapshot, live], "4.20.46", ["4.22.0"])
    assert (plan["channel"], plan["catalog_source"]) == ("stable-2.17", "redhat-operators")
    # 4.19 hosted: newest allowed is 2.11, in both catalogs; redhat-operators wins the tie.
    plan = F.mce_channel([snapshot, live], "4.20.46", ["4.19.0"])
    assert (plan["channel"], plan["catalog_source"]) == ("stable-2.11", "redhat-operators")
    blocked = F.mce_channel([snapshot], "4.20.46", ["4.22.0"])
    assert blocked["ok"] is False and "redhat-operators-snapshot-lightspeed" in blocked["message"]
    virt = [_package("kubevirt-hyperconverged", ["stable"], source="snap"), _package("kubevirt-hyperconverged", ["stable"])]
    assert F.preferred_package(virt)["catalog_source"] == "redhat-operators"
    assert F.preferred_package(virt[:1])["catalog_source"] == "snap"
    assert F.preferred_package([])["present"] is False
    facts = _bare_facts()
    facts["clusterversion"]["version"] = "4.20.46"
    facts["packages"]["mce"] = [snapshot, live]
    report = F.prereq_report(facts, [_cluster()], {"install_planned": ["mce", "virtualization", "metallb"],
                                                   "metallb_address_pools": ["192.0.2.240-192.0.2.250"]})
    assert report["ready"] is True, [c["message"] for c in report["missing"]]
    assert report["install_plan"]["mce"]["catalog_source"] == "redhat-operators"


def test_install_prerequisites_reports_planned_items_not_missing():
    clusters = [_cluster(require_live_migration=True)]
    settings = {"install_planned": ["mce", "virtualization", "metallb"], "metallb_address_pools": ["192.0.2.240-192.0.2.250"]}
    report = F.prereq_report(_bare_facts(), clusters, settings)
    assert report["ready"] is True, [c["message"] for c in report["missing"]]
    planned = {c["id"] for c in report["planned"]}
    assert {"mce.installed", "hypershift.operator", "virt.installed", "virt.apis", "ingress.load_balancer"} <= planned
    assert report["summary"]["planned"] == len(report["planned"])
    # The matrix check uses the MCE version that will be installed.
    assert {c["id"]: c["status"] for c in report["checks"]}["matrix.hosted"] == "pass"
    # RWX is only known after CDI exists, so it is rechecked by deploy.
    assert "storage.live_migration" in {c["id"] for c in report["optimizations"]}
    lines = F.prereq_summary_lines(report)
    assert any(line.startswith("[WILL INSTALL] mce.installed") for line in lines)
    plan = report["install_plan"]
    assert plan["mce"]["channel"] == "stable-2.17" and plan["mce"]["catalog_source"] == "redhat-operators"
    assert plan["virtualization"]["channel"] == "stable"
    assert plan["metallb"]["address_pools"] == ["192.0.2.240-192.0.2.250"]
    assert F.prereq_report(_ready_facts(), clusters, settings)["install_plan"] == {}


def test_install_prerequisites_still_fails_what_it_cannot_install():
    settings = {"install_planned": ["mce", "virtualization", "metallb"]}
    facts = _bare_facts()
    facts["packages"].pop("virtualization")
    report = F.prereq_report(facts, [_cluster()], settings)
    assert {"virt.installed", "ingress.load_balancer"} <= _missing(report)  # no package, no address pool
    facts = _bare_facts()
    facts["clusterversion"]["version"] = "4.18.9"
    report = F.prereq_report(facts, [_cluster()], settings)
    assert "mce.installed" in _missing(report)  # no MCE channel hosts 4.22 on a 4.18 cluster
    assert "storage.default_class" in _missing(
        F.prereq_report(dict(_bare_facts(), storage_classes=[]), [_cluster()], settings)
    )


def test_without_install_prerequisites_nothing_is_planned():
    report = F.prereq_report(_bare_facts(), [_cluster()])
    assert report["planned"] == []
    assert {"mce.installed", "hypershift.operator", "virt.installed", "ingress.load_balancer"} <= _missing(report)


def test_access_reviews_cover_planned_installs():
    keys = {r["key"] for r in F.access_reviews([_cluster()], ["clusters"], install_planned=["mce", "virtualization", "metallb"])}
    assert "create subscriptions.operators.coreos.com in multicluster-engine" in keys
    assert "create multiclusterengines.multicluster.openshift.io (cluster scope)" in keys
    assert "create hyperconvergeds.hco.kubevirt.io in openshift-cnv" in keys
    assert "create ipaddresspools.metallb.io in metallb-system" in keys
    assert not any("subscriptions" in key for key in (r["key"] for r in F.access_reviews([_cluster()], ["clusters"])))


def test_planned_wildcard_remediation_is_not_a_missing_prerequisite():
    facts = _ready_facts()
    facts["ingress"]["wildcard_policy"] = "WildcardsDisallowed"
    report = F.prereq_report(facts, [_cluster()], {"wildcard_remediation_planned": True})
    assert report["ready"] is True
    custom = F.prereq_report(facts, [_cluster(base_domain="example.test")])
    assert "ingress.wildcard_routes" not in _missing(custom)


def test_live_migration_required_needs_rwx_profile():
    facts = _ready_facts()
    facts["storage_profiles"] = {"rwx": [{"access_modes": ["ReadWriteOnce"], "volume_mode": "Block"}]}
    report = F.prereq_report(facts, [_cluster(require_live_migration=True)])
    assert "storage.live_migration" in _missing(report)
    optional = F.prereq_report(facts, [_cluster()])
    assert optional["ready"] is True
    assert "storage.live_migration" in {c["id"] for c in optional["optimizations"]}


def test_existing_cluster_skips_creation_checks():
    facts = _ready_facts()
    facts["existing_hostedclusters"] = [{"name": "tenant-a", "namespace": "clusters"}]
    facts["managed_clusters"] = ["local-cluster", "tenant-a"]
    facts["nodes"] = [dict(n, cpu_allocatable_m=1000) for n in facts["nodes"]]
    report = F.prereq_report(facts, [_cluster()])
    assert "cluster.unique_name" not in _missing(report)
    assert "management.capacity" not in _missing(report)
    assert any(c["id"] == "cluster.exists" for c in report["checks"])


def test_disconnected_checks():
    facts = _ready_facts()
    c = _cluster(release_image="m.example:5000/ocp/release@" + DIGEST, hosted_version="4.22.0",
                 disconnected={"enabled": True,
                               "image_content_sources": [{"source": "quay.io/openshift-release-dev/ocp-release",
                                                          "mirrors": ["m.example:5000/ocp/release"]}]})
    report = F.prereq_report(facts, [c])
    assert "disconnected.mirrors" in _missing(report)
    facts["mirror_sources"] = list(F.RELEASE_REPOS)
    facts["pull_secrets"]["tenant-a"]["registries"] = ["quay.io"]
    report = F.prereq_report(facts, [c])
    assert report["ready"] is True
    warns = {x["id"] for x in report["optimizations"]}
    assert {"disconnected.mirror_auth", "disconnected.trust", "disconnected.management_ca"} <= warns


def test_fips_needs_fips_management_cluster():
    report = F.prereq_report(_ready_facts(), [_cluster(fips=True)])
    assert "cluster.fips" in _missing(report)


def test_summary_lines_list_failures_first():
    facts = _ready_facts()
    facts["network"]["type"] = "OpenShiftSDN"
    lines = F.prereq_summary_lines(F.prereq_report(facts, [_cluster()]))
    assert lines[0].startswith("NOT READY")
    assert lines[2].startswith("[MISSING] network.ovn")


# ------------------------------------------------------------- fact shaping


def test_node_and_pod_facts():
    nodes = F.node_facts([{
        "metadata": {"name": "w1", "labels": {"node-role.kubernetes.io/worker": "", "topology.kubernetes.io/zone": "z1"}},
        "spec": {},
        "status": {"allocatable": {"cpu": "15500m", "memory": "64Gi", "pods": "250"},
                   "conditions": [{"type": "Ready", "status": "True"}]},
    }])
    assert nodes == [{"name": "w1", "worker": True, "control_plane": False, "ready": True, "schedulable": True,
                      "cpu_allocatable_m": 15500, "memory_allocatable_b": 64 * 1024 ** 3,
                      "pods_allocatable": 250, "zone": "z1"}]
    pods = F.pod_requests([
        {"spec": {"nodeName": "w1", "containers": [{"resources": {"requests": {"cpu": "500m", "memory": "1Gi"}}},
                                                   {"resources": {"requests": {"cpu": "1"}}}],
                  "initContainers": [{"resources": {"requests": {"cpu": "2"}}}]},
         "status": {"phase": "Running"}},
        {"spec": {"nodeName": "w1", "containers": [{"resources": {"requests": {"cpu": "4"}}}]}, "status": {"phase": "Succeeded"}},
        {"spec": {"containers": []}, "status": {"phase": "Pending"}},
    ])
    assert pods == {"w1": {"cpu_m": 2000, "memory_b": 1024 ** 3, "pods": 1}}


def test_mce_storage_and_mirror_facts():
    mce = F.mce_facts([{"metadata": {"name": "multiclusterengine"},
                        "spec": {"overrides": {"components": [{"name": "hypershift", "enabled": False}]}},
                        "status": {"currentVersion": "2.17.1", "phase": "Available"}}])
    assert mce["hypershift_enabled"] is False and mce["hypershift_local_hosting_enabled"] is None
    assert F.mce_facts([]) == {"present": False}
    scs = F.storage_class_facts([{"metadata": {"name": "a", "annotations": {"storageclass.kubernetes.io/is-default-class": "true"}},
                                  "provisioner": "p"}])
    assert scs[0]["default"] is True
    profiles = F.storage_profile_facts([{"metadata": {"name": "a"},
                                         "status": {"claimPropertySets": [{"accessModes": ["ReadWriteMany"], "volumeMode": "Block"}]}}])
    assert profiles == {"a": [{"access_modes": ["ReadWriteMany"], "volume_mode": "Block"}]}
    sources = F.mirror_sources(
        [{"spec": {"imageDigestMirrors": [{"source": "quay.io/a", "mirrors": ["m/a"]}, {"source": "quay.io/nomirror"}]}}],
        [{"spec": {"repositoryDigestMirrors": [{"source": "quay.io/b", "mirrors": ["m/b"]}]}}],
    )
    assert sources == ["quay.io/a", "quay.io/b"]
    assert F.install_config_fips("apiVersion: v1\nfips: true\n") is True
    assert F.install_config_fips("apiVersion: v1\n") is False
    assert F.install_config_fips("") is None


def test_access_reviews_cover_deploy_needs():
    keys = {r["key"] for r in F.access_reviews([_cluster(base_domain="example.test")], [], True)}
    assert "create hostedclusters.hypershift.openshift.io in clusters" in keys
    assert "create namespaces (cluster scope)" in keys
    assert "get secrets/pull-secret in openshift-config" in keys
    assert "create services in clusters-tenant-a" in keys
    assert "patch ingresscontrollers.operator.openshift.io/default in openshift-ingress-operator" in keys
    present = {r["key"] for r in F.access_reviews([_cluster(pull_secret_source="vault")], ["clusters"])}
    assert "create namespaces (cluster scope)" not in present
    assert not any("openshift-config" in k for k in present)


# ----------------------------------------------------------------- lifecycle


def _existing_hc(**spec_overrides):
    hc = F.hostedcluster_manifest(_cluster())
    hc["spec"]["infraID"] = "tenant-a-x7k2p"
    hc["spec"].update(spec_overrides)
    hc["status"] = {
        "conditions": [{"type": "Available", "status": "True"}, {"type": "ValidReleaseImage", "status": "True"}],
        "version": {"history": [{"version": "4.22.0", "state": "Completed", "image": RELEASE_422}]},
        "controlPlaneEndpoint": {"host": "192.0.2.50", "port": 6443},
        "kubeconfig": {"name": "tenant-a-admin-kubeconfig"},
        "kubeadminPassword": {"name": "tenant-a-kubeadmin-password"},
    }
    return hc


def test_immutable_drift_reports_differences_only():
    assert F.immutable_drift(_cluster(), _existing_hc()) == []
    drift = F.immutable_drift(_cluster(controller_availability_policy="SingleReplica",
                                       etcd_storage_class="lvms"), _existing_hc())
    assert {d["field"] for d in drift} == {"controllerAvailabilityPolicy", "etcd storageClassName"}


def test_hostedcluster_status_and_blocking_conditions():
    status = F.hostedcluster_status(_existing_hc())
    assert status["available"] and status["version"] == "4.22.0" and status["version_state"] == "Completed"
    assert status["api_url"] == "https://192.0.2.50:6443"
    bad = _existing_hc()
    bad["status"]["conditions"].append({"type": "ValidReleaseImage", "status": "False", "reason": "PullFailed"})
    bad["status"]["conditions"] = [c for c in bad["status"]["conditions"] if not (c["type"] == "ValidReleaseImage" and c["status"] == "True")]
    assert F.hostedcluster_status(bad)["blocking_conditions"][0]["type"] == "ValidReleaseImage"
    assert F.hostedcluster_status({})["exists"] is False


def test_hostedcluster_status_completed_version_ignores_rollout_in_progress():
    hc = _existing_hc()
    hc["status"]["version"]["history"].insert(0, {"version": "4.22.1", "state": "Partial"})
    status = F.hostedcluster_status(hc)
    assert (status["version"], status["version_state"], status["completed_version"]) == ("4.22.1", "Partial", "4.22.0")
    assert F.hostedcluster_status({"spec": {}})["completed_version"] == ""


def test_hosted_auth_pins_current_context_values():
    kubeconfig = {
        "current-context": "admin",
        "clusters": [
            {"name": "other", "cluster": {"server": "https://wrong.example.test:6443"}},
            {"name": "hosted", "cluster": {"server": "https://api.tenant-a.example.test:6443",
                                           "certificate-authority-data": "Q0E="}},
        ],
        "users": [{"name": "admin", "user": {"client-certificate-data": "Y2VydA==", "client-key-data": "a2V5"}}],
        "contexts": [{"name": "admin", "context": {"cluster": "hosted", "user": "admin"}}],
    }
    auth = F.hosted_auth(kubeconfig)
    assert auth == {"context": "admin", "host": "https://api.tenant-a.example.test:6443", "api_key": "",
                    "validate_certs": True, "ca_data": "Q0E=", "ca_file": ""}
    kubeconfig["clusters"][1]["cluster"] = {"server": "https://192.0.2.10:31000", "insecure-skip-tls-verify": True}
    kubeconfig["users"][0]["user"] = {"token": "t0ken"}
    auth = F.hosted_auth(kubeconfig)
    assert (auth["validate_certs"], auth["api_key"], auth["ca_data"]) == (False, "t0ken", "")
    assert F.hosted_auth(None)["host"] == ""


def test_nodepool_status_convergence():
    np = F.nodepool_manifest(_cluster())
    np["status"] = {"replicas": 2, "version": "4.22.0",
                    "conditions": [{"type": "Ready", "status": "True"},
                                   {"type": "KubeVirtNodesLiveMigratable", "status": "False", "message": "not shared"}]}
    status = F.nodepool_status(np)
    assert status["converged"] is True
    assert status["live_migratable"] == {"status": "False", "message": "not shared"}
    np["status"]["replicas"] = 1
    assert F.nodepool_status(np)["converged"] is False


@pytest.mark.parametrize(
    "current,target,supported,pools,mode,ok",
    [
        ("4.21.5", "4.22.0", ["4.22", "4.21"], ["4.21.5"], "controlplane", True),
        ("4.22.0", "4.21.9", ["4.22", "4.21"], [], "controlplane", False),  # downgrade
        ("4.21.5", "4.22.0", ["4.21", "4.20"], [], "controlplane", False),  # MCE not updated yet
        ("4.21.5", "4.22.0", ["4.22"], ["4.18.3"], "controlplane", False),  # pool would be 4 minors behind
        ("4.22.0", "4.22.0", [], [], "nodepool", True),
        ("4.22.0", "4.22.1", [], [], "nodepool", False),  # pool newer than control plane (patch)
        ("4.22.0", "4.18.9", [], [], "nodepool", False),  # more than 3 minors behind
        ("4.22.0", "4.19.9", [], [], "nodepool", True),
        ("", "4.22.0", [], [], "nodepool", False),  # control plane never reported a completed version
    ],
)
def test_upgrade_check(current, target, supported, pools, mode, ok):
    assert F.upgrade_check(current, target, supported, pools, mode)["ok"] is ok


def test_upgrade_check_warns_on_multi_minor_jump():
    out = F.upgrade_check("4.20.1", "4.22.0", ["4.22", "4.21", "4.20"], [], "controlplane")
    assert out["ok"] is True
    assert any("one minor version at a time" in w for w in out["warnings"])


def test_access_summary_has_no_secret_values():
    summary = F.access_summary(_existing_hc(), "apps.mgmt.example.test")
    assert summary["api_url"] == "https://192.0.2.50:6443"
    assert summary["console_url"] == "https://console-openshift-console.apps.tenant-a.apps.mgmt.example.test"
    assert summary["kubeconfig_secret"] == {"namespace": "clusters", "name": "tenant-a-admin-kubeconfig", "key": "kubeconfig"}
    assert "oc extract -n clusters secret/tenant-a-admin-kubeconfig" in summary["extract_kubeconfig_command"]


def test_filter_registration():
    filters = F.FilterModule().filters()
    for name in ("hcp_kubevirt_prereq_report", "hcp_kubevirt_hostedcluster_manifest",
                 "hcp_kubevirt_nodepool_manifest", "hcp_kubevirt_upgrade_check", "hcp_kubevirt_access_reviews",
                 "hcp_kubevirt_hosted_auth", "hcp_kubevirt_package_facts", "hcp_kubevirt_mce_channel",
                 "hcp_kubevirt_package_options", "hcp_kubevirt_preferred_package"):
        assert callable(filters[name])
