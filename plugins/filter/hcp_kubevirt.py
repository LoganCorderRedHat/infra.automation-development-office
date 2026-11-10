# SPDX-License-Identifier: GPL-3.0-or-later
"""Hosted control planes (HyperShift) on OpenShift Virtualization helpers.

These filters back the Shift on Shift roles (``ocp_hcp_kubevirt_prereqs`` and
``ocp_hcp_kubevirt_cluster``). They are pure functions: roles gather cluster
state with ``kubernetes.core`` and pass it in, so every decision is unit
testable without a cluster.

Field names and defaults follow the ``hypershift.openshift.io/v1beta1`` API
(HyperShift release-4.22) and the OpenShift 4.22 "Hosted control planes"
documentation for the KubeVirt platform. Nothing here enables a Technology
Preview field (GPU host devices, tolerations, external infrastructure).
"""

from __future__ import annotations

import copy
import ipaddress
import json
import re

HYPERSHIFT_API = "hypershift.openshift.io/v1beta1"
MANAGED_BY_LABEL = "app.kubernetes.io/managed-by"
MANAGED_BY_VALUE = "infra.automation_development_office"
PART_OF_LABEL = "app.kubernetes.io/part-of"
PART_OF_VALUE = "shift-on-shift"
INSTANCE_LABEL = "app.kubernetes.io/instance"
# Same label ``hcp create cluster`` puts on the secrets it renders.
SAFE_TO_DELETE_LABEL = "hypershift.openshift.io/safe-to-delete-with-cluster"

_DNS_LABEL_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
_DNS_SUBDOMAIN_RE = re.compile(
    r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$"
)
_QUANTITY_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)?)(Ki|Mi|Gi|Ti|Pi|Ei|k|M|G|T|P|E)?$")
_VERSION_RE = re.compile(r"(?<![0-9.])([1-9][0-9]*)\.([0-9]+)(?:\.([0-9]+))?")
_IMAGE_RE = re.compile(
    r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:[0-9]+)?(/[a-z0-9._/-]+)+"
    r"(:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}|@sha256:[a-f0-9]{64})$"
)
_CHANNEL_RE = re.compile(r"^(stable|fast|candidate|eus)-[1-9][0-9]*\.[0-9]+$")
_NAD_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?/[a-z0-9]([-a-z0-9]*[a-z0-9])?$")

PULL_SECRET_SOURCES = ("management_cluster", "vault", "existing_secret")
API_PUBLISHING = ("LoadBalancer", "NodePort")
AVAILABILITY_POLICIES = ("HighlyAvailable", "SingleReplica")
ACCESS_MODES = ("ReadWriteMany", "ReadWriteOnce")
VOLUME_MODES = ("Block", "Filesystem")
CACHE_STRATEGIES = ("None", "PVC")
MULTIQUEUE = ("Enable", "Disable")
QOS_CLASSES = ("Burstable", "Guaranteed")
UPGRADE_TYPES = ("Replace", "InPlace")
OLM_PLACEMENTS = ("management", "guest")
# OpenShift 4.22 docs, "Capabilities that you can enable or disable".
CAPABILITIES = (
    "ImageRegistry",
    "openshift-samples",
    "Insights",
    "baremetal",
    "Console",
    "NodeTuning",
    "Ingress",
)
# Disabling these needs a 4.20 or later hosted cluster.
CAPABILITIES_DISABLE_420 = ("openshift-samples", "Insights", "Console", "NodeTuning", "Ingress")
OLM_CATALOG_ANNOTATIONS = {
    "redhat_operators": "hypershift.openshift.io/redhat-operators-catalog-image",
    "certified_operators": "hypershift.openshift.io/certified-operators-catalog-image",
    "community_operators": "hypershift.openshift.io/community-operators-catalog-image",
    "redhat_marketplace": "hypershift.openshift.io/redhat-marketplace-catalog-image",
}
OLM_REGISTRY_OVERRIDES_ANNOTATION = "hypershift.openshift.io/olm-catalogs-is-registry-overrides"
# Namespaces a hosted cluster must never be created in.
RESERVED_NAMESPACES = frozenset(
    {
        "default",
        "hypershift",
        "local-cluster",
        "multicluster-engine",
        "open-cluster-management",
        "openshift",
        "openshift-cnv",
    }
)
RELEASE_REPOS = (
    "quay.io/openshift-release-dev/ocp-release",
    "quay.io/openshift-release-dev/ocp-v4.0-art-dev",
)

# OpenShift 4.22 "Support matrix for hosted control planes": management and
# hosted cluster versions per multicluster engine Operator release, and the
# OpenShift Virtualization platform row ("Hosted cluster platform support").
# Roles accept an override with the same shape.
SUPPORT_MATRIX = {
    "mce": {
        "2.6": {"management": ["4.14", "4.16"], "hosted": ["4.14", "4.16"]},
        "2.7": {"management": ["4.16"], "hosted": ["4.14", "4.16"]},
        "2.8": {"management": ["4.16", "4.18"], "hosted": ["4.14", "4.16", "4.18"]},
        "2.9": {"management": ["4.18", "4.19"], "hosted": ["4.16", "4.18", "4.19"]},
        "2.10": {"management": ["4.18", "4.19", "4.20"], "hosted": ["4.18", "4.19", "4.20"]},
        "2.11": {"management": ["4.19", "4.20", "4.21"], "hosted": ["4.19", "4.20", "4.21"]},
        "2.17": {"management": ["4.20", "4.21", "4.22"], "hosted": ["4.20", "4.21", "4.22"]},
    },
    "kubevirt_platform": {
        "management": ["4.14", "4.16", "4.18", "4.19", "4.20", "4.21", "4.22"],
        "hosted": ["4.14", "4.16", "4.18", "4.19", "4.20", "4.21", "4.22"],
    },
}

# Prerequisites the deploy action can install when install_prerequisites is
# on: OLM package, install namespace, and what the report calls them.
INSTALLABLE = {
    "mce": {"package": "multicluster-engine", "namespace": "multicluster-engine",
            "label": "multicluster engine Operator"},
    "virtualization": {"package": "kubevirt-hyperconverged", "namespace": "openshift-cnv",
                       "label": "OpenShift Virtualization"},
    "metallb": {"package": "metallb-operator", "namespace": "metallb-system", "label": "MetalLB"},
}

DEFAULTS = {
    "namespace": "clusters",
    "release_image": "",
    "hosted_version": "",
    "pull_secret_source": "management_cluster",
    "pull_secret_name": "",
    "ssh_public_key": "",
    "base_domain": "",
    "controller_availability_policy": "HighlyAvailable",
    "api_publishing": "LoadBalancer",
    "api_server_address": "",
    "cluster_network_cidr": "10.132.0.0/14",
    "service_network_cidr": "172.31.0.0/16",
    "machine_network_cidr": "",
    "etcd_storage_class": "",
    "etcd_storage_size": "8Gi",
    "nodepool_name": "",
    "worker_count": 2,
    "autoscaling_min": 0,
    "autoscaling_max": 0,
    "worker_cores": 2,
    "worker_memory": "8Gi",
    "root_volume_size": "32Gi",
    "root_volume_storage_class": "",
    "root_volume_access_mode": "",
    "root_volume_volume_mode": "",
    "root_volume_cache_strategy": "None",
    "network_multiqueue": "Enable",
    "qos_class": "Burstable",
    "vm_node_selector": {},
    "additional_networks": [],
    "attach_default_network": True,
    "node_upgrade_type": "Replace",
    "auto_repair": False,
    "storage_class_mappings": [],
    "volume_snapshot_class_mappings": [],
    "capabilities_enabled": [],
    "capabilities_disabled": [],
    "channel": "",
    "fips": False,
    "require_live_migration": False,
    "create_apps_load_balancer": True,
    "disconnected": {
        "enabled": False,
        "image_content_sources": [],
        "additional_trust_bundle": "",
        "olm_catalog_placement": "management",
        "disable_default_sources": False,
        "olm_catalog_images": {},
        "olm_registry_overrides": "",
    },
}


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def _as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on", "y")


def _as_int(value, default=0):
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return int(value)
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _text(value):
    return "" if value is None else str(value).strip()


def _split_list(value):
    """Accept a list or a comma/newline separated string."""
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        return [_text(item) for item in value if _text(item)]
    return [part.strip() for part in re.split(r"[,\n]", str(value)) if part.strip()]


def _key_value_map(value):
    """Accept a dict or a ``k=v,k2=v2`` string."""
    if not value:
        return {}
    if isinstance(value, dict):
        return {_text(k): _text(v) for k, v in value.items() if _text(k)}
    out = {}
    for part in _split_list(value):
        key, _sep, val = part.partition("=")
        if _text(key):
            out[_text(key)] = _text(val)
    return out


def _class_mappings(value, infra_key, guest_key):
    """Normalize storage/snapshot class mappings.

    Accepts dicts (``infra_*``/``guest_*``/``group``) or the ``hcp`` CLI string
    form ``<infra>/<guest>[,group=<name>]``.
    """
    out = []
    for item in value or []:
        if isinstance(item, dict):
            infra = _text(item.get(infra_key) or item.get("infra"))
            guest = _text(item.get(guest_key) or item.get("guest"))
            group = _text(item.get("group"))
        else:
            text = _text(item)
            mapping, _sep, rest = text.partition(",")
            infra, _slash, guest = mapping.partition("/")
            group = ""
            if rest.startswith("group="):
                group = rest[len("group="):]
            infra, guest, group = _text(infra), _text(guest), _text(group)
        if infra or guest:
            out.append({"infra": infra, "guest": guest, "group": group})
    return out


def _image_content_sources(value):
    out = []
    for item in value or []:
        if not isinstance(item, dict):
            continue
        source = _text(item.get("source"))
        mirrors = _split_list(item.get("mirrors"))
        if source or mirrors:
            out.append({"source": source, "mirrors": mirrors})
    return out


def quantity_to_bytes(value):
    """Convert a Kubernetes quantity string to bytes (int) or None."""
    text = _text(value)
    match = _QUANTITY_RE.match(text)
    if not match:
        return None
    number = float(match.group(1))
    suffix = match.group(2) or ""
    binary = {"Ki": 1, "Mi": 2, "Gi": 3, "Ti": 4, "Pi": 5, "Ei": 6}
    decimal = {"k": 1, "M": 2, "G": 3, "T": 4, "P": 5, "E": 6}
    if suffix in binary:
        return int(number * (1024 ** binary[suffix]))
    if suffix in decimal:
        return int(number * (1000 ** decimal[suffix]))
    return int(number)


def cpu_to_millicores(value):
    """Convert a CPU quantity (``2``, ``500m``, ``1.5``) to millicores."""
    text = _text(value)
    if not text:
        return 0
    try:
        if text.endswith("m"):
            return int(float(text[:-1]))
        return int(float(text) * 1000)
    except ValueError:
        return 0


def parse_version(value):
    """Return ``x.y.z`` (or ``x.y``) found in a version or release image string.

    Digest-pinned images carry no version and return an empty string.
    """
    text = _text(value)
    if not text:
        return ""
    if "@sha256:" in text:
        return ""
    if ":" in text and "/" in text:
        text = text.rsplit(":", 1)[1]
    match = _VERSION_RE.search(text)
    if not match:
        return ""
    major, minor, patch = match.group(1), match.group(2), match.group(3)
    return f"{major}.{minor}.{patch}" if patch is not None else f"{major}.{minor}"


def minor_version(value):
    """Return ``x.y`` from a version or release image string."""
    version = parse_version(value)
    if not version:
        return ""
    return ".".join(version.split(".")[:2])


def _version_tuple(value):
    version = parse_version(value)
    if not version:
        return ()
    return tuple(int(part) for part in version.split("."))


def version_compare(left, right):
    """Compare two versions. Returns -1, 0, 1 (missing patch counts as 0)."""
    lval = list(_version_tuple(left)) + [0, 0, 0]
    rval = list(_version_tuple(right)) + [0, 0, 0]
    lval, rval = lval[:3], rval[:3]
    if lval < rval:
        return -1
    if lval > rval:
        return 1
    return 0


def _minor_distance(newer, older):
    new = _version_tuple(newer)
    old = _version_tuple(older)
    if len(new) < 2 or len(old) < 2:
        return None
    if new[0] != old[0]:
        return None
    return new[1] - old[1]


# --------------------------------------------------------------------------
# cluster definition normalization and validation
# --------------------------------------------------------------------------


def normalize_cluster(cluster, defaults=None):
    """Merge a hosted cluster definition with defaults and normalize types."""
    merged = copy.deepcopy(DEFAULTS)
    for source in (defaults or {}, cluster or {}):
        for key, value in source.items():
            if key == "disconnected" and isinstance(value, dict):
                merged["disconnected"].update(copy.deepcopy(value))
            elif value is not None:
                merged[key] = copy.deepcopy(value)

    name = _text(merged.get("name")).lower()
    namespace = _text(merged.get("namespace")).lower() or DEFAULTS["namespace"]
    release_image = _text(merged.get("release_image"))
    hosted_version = parse_version(merged.get("hosted_version")) or parse_version(release_image)
    source = _text(merged.get("pull_secret_source")) or "management_cluster"
    pull_secret_name = _text(merged.get("pull_secret_name"))
    if source != "existing_secret" or not pull_secret_name:
        pull_secret_name = f"{name}-pull-secret" if source != "existing_secret" else ""
    ssh_key = _text(merged.get("ssh_public_key"))
    base_domain = _text(merged.get("base_domain")).lower().strip(".")
    autoscale_min = _as_int(merged.get("autoscaling_min"), 0)
    autoscale_max = _as_int(merged.get("autoscaling_max"), 0)
    autoscaling = None
    if (autoscale_max or 0) > 0:
        autoscaling = {"min": autoscale_min, "max": autoscale_max}
    disconnected = merged.get("disconnected") or {}
    olm_images = {
        key: _text((disconnected.get("olm_catalog_images") or {}).get(key))
        for key in OLM_CATALOG_ANNOTATIONS
    }
    trust_bundle = _text(disconnected.get("additional_trust_bundle"))
    access_mode = _text(merged.get("root_volume_access_mode"))
    volume_mode = _text(merged.get("root_volume_volume_mode"))
    require_live_migration = _as_bool(merged.get("require_live_migration"))
    if require_live_migration and not access_mode:
        access_mode = "ReadWriteMany"
    if require_live_migration and not volume_mode:
        # The docs recommend Block: Filesystem degrades hosted Block performance.
        volume_mode = "Block"

    return {
        "name": name,
        "namespace": namespace,
        "hcp_namespace": f"{namespace}-{name}" if name else "",
        "release_image": release_image,
        "hosted_version": hosted_version,
        "hosted_minor": minor_version(hosted_version),
        "pull_secret_source": source,
        "pull_secret_name": pull_secret_name,
        "ssh_public_key": ssh_key,
        "ssh_key_secret_name": f"{name}-ssh-key" if ssh_key and name else "",
        "etcd_encryption_secret_name": f"{name}-etcd-encryption-key" if name else "",
        "base_domain": base_domain,
        "base_domain_passthrough": not base_domain,
        "controller_availability_policy": _text(merged.get("controller_availability_policy")),
        "api_publishing": _text(merged.get("api_publishing")) or "LoadBalancer",
        "api_server_address": _text(merged.get("api_server_address")),
        "networking": {
            "network_type": "OVNKubernetes",
            "cluster_cidr": _split_list(merged.get("cluster_network_cidr")),
            "service_cidr": _split_list(merged.get("service_network_cidr")),
            "machine_cidr": _split_list(merged.get("machine_network_cidr")),
        },
        "etcd": {
            "storage_class": _text(merged.get("etcd_storage_class")),
            "size": _text(merged.get("etcd_storage_size")) or "8Gi",
        },
        "nodepool": {
            "name": (_text(merged.get("nodepool_name")).lower() or name),
            "replicas": None if autoscaling else _as_int(merged.get("worker_count"), 2),
            "autoscaling": autoscaling,
            "cores": _as_int(merged.get("worker_cores"), 2),
            "memory": _text(merged.get("worker_memory")) or "8Gi",
            "root_volume": {
                "size": _text(merged.get("root_volume_size")) or "32Gi",
                "storage_class": _text(merged.get("root_volume_storage_class")),
                "access_mode": access_mode,
                "volume_mode": volume_mode,
            },
            "cache_strategy": _text(merged.get("root_volume_cache_strategy")) or "None",
            "multiqueue": _text(merged.get("network_multiqueue")) or "Enable",
            "qos_class": _text(merged.get("qos_class")) or "Burstable",
            "node_selector": _key_value_map(merged.get("vm_node_selector")),
            "additional_networks": _split_list(merged.get("additional_networks")),
            "attach_default_network": _as_bool(merged.get("attach_default_network"), True),
            "upgrade_type": _text(merged.get("node_upgrade_type")) or "Replace",
            "auto_repair": _as_bool(merged.get("auto_repair")),
            "arch": "amd64",
        },
        "storage_class_mappings": _class_mappings(
            merged.get("storage_class_mappings"), "infra_storage_class", "guest_storage_class"
        ),
        "volume_snapshot_class_mappings": _class_mappings(
            merged.get("volume_snapshot_class_mappings"),
            "infra_volume_snapshot_class",
            "guest_volume_snapshot_class",
        ),
        "capabilities": {
            "enabled": _split_list(merged.get("capabilities_enabled")),
            "disabled": _split_list(merged.get("capabilities_disabled")),
        },
        "channel": _text(merged.get("channel")),
        "fips": _as_bool(merged.get("fips")),
        "require_live_migration": require_live_migration,
        "create_apps_load_balancer": bool(base_domain)
        and _as_bool(merged.get("create_apps_load_balancer"), True),
        "disconnected": {
            "enabled": _as_bool(disconnected.get("enabled")),
            "image_content_sources": _image_content_sources(
                disconnected.get("image_content_sources")
            ),
            "additional_trust_bundle": trust_bundle,
            "olm_catalog_placement": _text(disconnected.get("olm_catalog_placement"))
            or "management",
            "disable_default_sources": _as_bool(disconnected.get("disable_default_sources")),
            "olm_catalog_images": olm_images,
            "olm_registry_overrides": _text(disconnected.get("olm_registry_overrides")),
        },
        # Per-cluster name: hosted clusters sharing a namespace must not overwrite
        # each other's bundle (spec.additionalTrustBundle is only a reference).
        "trust_bundle_configmap_name": f"{name}-user-ca-bundle" if trust_bundle and name else "",
    }


def _cidr_errors(label, values):
    errors = []
    networks = []
    for value in values:
        try:
            networks.append(ipaddress.ip_network(value, strict=True))
        except ValueError:
            errors.append(f"{label} '{value}' is not a valid CIDR")
    return errors, networks


def cluster_errors(normalized):
    """Return a list of human-readable input errors for a normalized cluster."""
    cluster = normalized or {}
    errors = []
    name = cluster.get("name", "")
    namespace = cluster.get("namespace", "")
    nodepool = cluster.get("nodepool") or {}

    if not name:
        errors.append("name is required")
    elif not _DNS_LABEL_RE.match(name) or len(name) > 63:
        errors.append(f"name '{name}' must be a lowercase RFC 1123 label")
    elif name == "clusters":
        errors.append("name must not be 'clusters' (reserved by the hosted control planes docs)")
    if not _DNS_LABEL_RE.match(namespace or ""):
        errors.append(f"namespace '{namespace}' must be a lowercase RFC 1123 label")
    elif namespace in RESERVED_NAMESPACES or namespace.startswith(("kube-", "openshift-")):
        errors.append(f"namespace '{namespace}' is reserved; use a dedicated namespace such as 'clusters'")
    if name and namespace and name == namespace:
        errors.append(
            "namespace must differ from the hosted cluster name: the hosted cluster is "
            "imported as a managed cluster whose namespace is its name"
        )
    if name and namespace and len(f"{namespace}-{name}") > 63:
        errors.append(
            f"'{namespace}-{name}' (the hosted control plane namespace) exceeds 63 characters"
        )

    image = cluster.get("release_image", "")
    if not image:
        errors.append("release_image is required (for example quay.io/openshift-release-dev/ocp-release:4.22.0-multi)")
    elif not _IMAGE_RE.match(image):
        errors.append(f"release_image '{image}' is not a valid image reference with a tag or sha256 digest")
    if image and not cluster.get("hosted_version"):
        errors.append(
            "hosted_version is required when the release image has no version tag "
            "(for example a digest-pinned image); set it to the OpenShift version, e.g. 4.22.0"
        )

    if cluster.get("pull_secret_source") not in PULL_SECRET_SOURCES:
        errors.append(f"pull_secret_source must be one of {', '.join(PULL_SECRET_SOURCES)}")
    elif cluster.get("pull_secret_source") == "existing_secret" and not cluster.get("pull_secret_name"):
        errors.append("pull_secret_name is required when pull_secret_source is existing_secret")
    if cluster.get("pull_secret_name") and not _DNS_SUBDOMAIN_RE.match(cluster["pull_secret_name"]):
        errors.append(f"pull_secret_name '{cluster['pull_secret_name']}' is not a valid secret name")

    if cluster.get("controller_availability_policy") not in AVAILABILITY_POLICIES:
        errors.append(f"controller_availability_policy must be one of {', '.join(AVAILABILITY_POLICIES)}")
    if cluster.get("api_publishing") not in API_PUBLISHING:
        errors.append(f"api_publishing must be one of {', '.join(API_PUBLISHING)}")
    elif cluster.get("api_publishing") == "NodePort" and not cluster.get("api_server_address"):
        errors.append("api_server_address is required when api_publishing is NodePort")
    if cluster.get("base_domain") and not _DNS_SUBDOMAIN_RE.match(cluster["base_domain"]):
        errors.append(f"base_domain '{cluster['base_domain']}' is not a valid DNS domain")
    if cluster.get("ssh_public_key") and not re.match(
        r"^(ssh-(rsa|ed25519|dss)|ecdsa-sha2-nistp(256|384|521)|sk-[a-z0-9-]+@openssh\.com) ",
        cluster["ssh_public_key"],
    ):
        errors.append("ssh_public_key does not look like an OpenSSH public key")

    networking = cluster.get("networking") or {}
    all_networks = []
    for label, key in (
        ("cluster_network_cidr", "cluster_cidr"),
        ("service_network_cidr", "service_cidr"),
        ("machine_network_cidr", "machine_cidr"),
    ):
        cidr_errors, networks = _cidr_errors(label, networking.get(key) or [])
        errors.extend(cidr_errors)
        all_networks.extend((label, net) for net in networks)
    if not networking.get("cluster_cidr"):
        errors.append("cluster_network_cidr is required")
    if not networking.get("service_cidr"):
        errors.append("service_network_cidr is required")
    for index, (label_a, net_a) in enumerate(all_networks):
        for label_b, net_b in all_networks[index + 1:]:
            if net_a.version == net_b.version and net_a.overlaps(net_b):
                errors.append(f"{label_a} {net_a} overlaps {label_b} {net_b}")

    etcd = cluster.get("etcd") or {}
    if quantity_to_bytes(etcd.get("size")) is None:
        errors.append(f"etcd_storage_size '{etcd.get('size')}' is not a valid quantity (for example 8Gi)")

    if not nodepool.get("name") or not _DNS_LABEL_RE.match(nodepool["name"]):
        errors.append(f"nodepool_name '{nodepool.get('name')}' must be a lowercase RFC 1123 label")
    autoscaling = nodepool.get("autoscaling")
    if autoscaling:
        if autoscaling.get("min") is None or autoscaling["min"] < 1:
            errors.append("autoscaling_min must be at least 1 (scale from zero is AWS only)")
        if autoscaling.get("max") is None or autoscaling["max"] < (autoscaling.get("min") or 1):
            errors.append("autoscaling_max must be greater than or equal to autoscaling_min")
    else:
        replicas = nodepool.get("replicas")
        if replicas is None or replicas < 0:
            errors.append("worker_count must be an integer of 0 or greater")
    cores = nodepool.get("cores")
    if cores is None or cores < 1:
        errors.append("worker_cores must be an integer of 1 or greater")
    if quantity_to_bytes(nodepool.get("memory")) is None:
        errors.append(f"worker_memory '{nodepool.get('memory')}' is not a valid quantity (for example 16Gi)")
    root = nodepool.get("root_volume") or {}
    if quantity_to_bytes(root.get("size")) is None:
        errors.append(f"root_volume_size '{root.get('size')}' is not a valid quantity (for example 32Gi)")
    if root.get("access_mode") and root["access_mode"] not in ACCESS_MODES:
        errors.append(f"root_volume_access_mode must be one of {', '.join(ACCESS_MODES)}")
    if root.get("volume_mode") and root["volume_mode"] not in VOLUME_MODES:
        errors.append(f"root_volume_volume_mode must be one of {', '.join(VOLUME_MODES)}")
    if cluster.get("require_live_migration") and root.get("access_mode") != "ReadWriteMany":
        errors.append("require_live_migration needs root_volume_access_mode ReadWriteMany")
    for label, key, allowed in (
        ("root_volume_cache_strategy", "cache_strategy", CACHE_STRATEGIES),
        ("network_multiqueue", "multiqueue", MULTIQUEUE),
        ("qos_class", "qos_class", QOS_CLASSES),
        ("node_upgrade_type", "upgrade_type", UPGRADE_TYPES),
    ):
        if nodepool.get(key) not in allowed:
            errors.append(f"{label} must be one of {', '.join(allowed)}")
    for network in nodepool.get("additional_networks") or []:
        if not _NAD_RE.match(network):
            errors.append(f"additional network '{network}' must be <namespace>/<name>")
    if not nodepool.get("attach_default_network", True) and not nodepool.get("additional_networks"):
        errors.append("attach_default_network can be false only when additional_networks are set")

    for label, key in (
        ("storage_class_mappings", "storage_class_mappings"),
        ("volume_snapshot_class_mappings", "volume_snapshot_class_mappings"),
    ):
        for mapping in cluster.get(key) or []:
            if not mapping.get("infra") or not mapping.get("guest"):
                errors.append(f"{label} entries need both an infrastructure and a guest class name")

    capabilities = cluster.get("capabilities") or {}
    enabled = capabilities.get("enabled") or []
    disabled = capabilities.get("disabled") or []
    for capability in enabled + disabled:
        if capability not in CAPABILITIES:
            errors.append(f"unknown capability '{capability}'; supported: {', '.join(CAPABILITIES)}")
    overlap = sorted(set(enabled) & set(disabled))
    if overlap:
        errors.append(f"capabilities cannot be both enabled and disabled: {', '.join(overlap)}")
    if "Ingress" in disabled and "Console" not in disabled:
        errors.append("disabling the Ingress capability requires disabling Console too")
    hosted = cluster.get("hosted_version", "")
    late = sorted(set(disabled) & set(CAPABILITIES_DISABLE_420))
    if late and hosted and version_compare(hosted, "4.20") < 0:
        errors.append(f"disabling {', '.join(late)} requires a 4.20 or later hosted cluster")

    channel = cluster.get("channel", "")
    if channel and not _CHANNEL_RE.match(channel):
        errors.append(f"channel '{channel}' must look like stable-4.22")

    disconnected = cluster.get("disconnected") or {}
    for entry in disconnected.get("image_content_sources") or []:
        if not entry.get("source") or not entry.get("mirrors"):
            errors.append("each image content source needs a source and at least one mirror")
    bundle = disconnected.get("additional_trust_bundle", "")
    if bundle and "-----BEGIN CERTIFICATE-----" not in bundle:
        errors.append("additional_trust_bundle must contain PEM certificates")
    if disconnected.get("olm_catalog_placement") not in OLM_PLACEMENTS:
        errors.append(f"olm_catalog_placement must be one of {', '.join(OLM_PLACEMENTS)}")
    for key, image_ref in (disconnected.get("olm_catalog_images") or {}).items():
        if image_ref and not _IMAGE_RE.match(image_ref):
            errors.append(f"olm_catalog_images.{key} '{image_ref}' is not a valid image reference")
    return errors


def cluster_definitions(clusters, defaults=None, selected=""):
    """Normalize a list of definitions and optionally select one by name.

    Returns ``{"clusters": [...], "errors": [...]}``. Errors include duplicate
    names and an unknown ``selected`` name.
    """
    normalized = [normalize_cluster(item, defaults) for item in (clusters or [])]
    errors = []
    names = [item["name"] for item in normalized if item["name"]]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        errors.append(f"duplicate hosted cluster names: {', '.join(duplicates)}")
    target = _text(selected).lower()
    if target:
        normalized = [item for item in normalized if item["name"] == target]
        if not normalized:
            errors.append(
                f"hosted cluster '{target}' is not defined; defined: {', '.join(names) or 'none'}"
            )
    for item in normalized:
        errors.extend(f"{item['name'] or '<unnamed>'}: {msg}" for msg in cluster_errors(item))
    return {"clusters": normalized, "errors": errors}


# --------------------------------------------------------------------------
# manifest rendering
# --------------------------------------------------------------------------


def _labels(cluster):
    return {
        MANAGED_BY_LABEL: MANAGED_BY_VALUE,
        PART_OF_LABEL: PART_OF_VALUE,
        INSTANCE_LABEL: cluster["name"],
    }


def _service_strategies(cluster):
    """Match ``hcp create cluster kubevirt`` service publishing output."""
    if cluster["api_publishing"] == "NodePort":
        address = cluster["api_server_address"]
        return [
            {"service": service, "servicePublishingStrategy": {"type": "NodePort", "nodePort": {"address": address}}}
            for service in ("APIServer", "OAuthServer", "OIDC", "Konnectivity", "Ignition")
        ]
    return [
        {"service": "APIServer", "servicePublishingStrategy": {"type": "LoadBalancer"}},
        {"service": "Ignition", "servicePublishingStrategy": {"type": "Route"}},
        {"service": "Konnectivity", "servicePublishingStrategy": {"type": "Route"}},
        {"service": "OAuthServer", "servicePublishingStrategy": {"type": "Route"}},
    ]


def hostedcluster_manifest(cluster):
    """Render the ``HostedCluster`` for a normalized definition."""
    net = cluster["networking"]
    etcd_volume = {"size": cluster["etcd"]["size"]}
    if cluster["etcd"]["storage_class"]:
        etcd_volume["storageClassName"] = cluster["etcd"]["storage_class"]
    kubevirt = {}
    if cluster["base_domain_passthrough"]:
        kubevirt["baseDomainPassthrough"] = True
    if cluster["storage_class_mappings"] or cluster["volume_snapshot_class_mappings"]:
        manual = {}
        if cluster["storage_class_mappings"]:
            manual["storageClassMapping"] = [
                {
                    key: value
                    for key, value in (
                        ("infraStorageClassName", item["infra"]),
                        ("guestStorageClassName", item["guest"]),
                        ("group", item["group"]),
                    )
                    if value
                }
                for item in cluster["storage_class_mappings"]
            ]
        if cluster["volume_snapshot_class_mappings"]:
            manual["volumeSnapshotClassMapping"] = [
                {
                    key: value
                    for key, value in (
                        ("infraVolumeSnapshotClassName", item["infra"]),
                        ("guestVolumeSnapshotClassName", item["guest"]),
                        ("group", item["group"]),
                    )
                    if value
                }
                for item in cluster["volume_snapshot_class_mappings"]
            ]
        kubevirt["storageDriver"] = {"type": "Manual", "manual": manual}

    networking = {
        "networkType": net["network_type"],
        "clusterNetwork": [{"cidr": cidr} for cidr in net["cluster_cidr"]],
        "serviceNetwork": [{"cidr": cidr} for cidr in net["service_cidr"]],
    }
    if net["machine_cidr"]:
        networking["machineNetwork"] = [{"cidr": cidr} for cidr in net["machine_cidr"]]

    disconnected = cluster["disconnected"]
    spec = {
        "release": {"image": cluster["release_image"]},
        "pullSecret": {"name": cluster["pull_secret_name"]},
        "sshKey": {"name": cluster["ssh_key_secret_name"]} if cluster["ssh_key_secret_name"] else {},
        "dns": {"baseDomain": cluster["base_domain"]},
        "networking": networking,
        "platform": {"type": "KubeVirt", "kubevirt": kubevirt},
        "etcd": {
            "managementType": "Managed",
            "managed": {"storage": {"type": "PersistentVolume", "persistentVolume": etcd_volume}},
        },
        "controllerAvailabilityPolicy": cluster["controller_availability_policy"],
        "secretEncryption": {
            "type": "aescbc",
            "aescbc": {"activeKey": {"name": cluster["etcd_encryption_secret_name"]}},
        },
        "services": _service_strategies(cluster),
        "fips": cluster["fips"],
        "olmCatalogPlacement": disconnected["olm_catalog_placement"],
        "configuration": {},
    }
    if disconnected["disable_default_sources"]:
        spec["configuration"]["operatorhub"] = {"disableAllDefaultSources": True}
    if disconnected["image_content_sources"]:
        spec["imageContentSources"] = [
            {"source": item["source"], "mirrors": list(item["mirrors"])}
            for item in disconnected["image_content_sources"]
        ]
    if cluster["trust_bundle_configmap_name"]:
        spec["additionalTrustBundle"] = {"name": cluster["trust_bundle_configmap_name"]}
    capabilities = {
        key: list(values) for key, values in cluster["capabilities"].items() if values
    }
    if capabilities:
        spec["capabilities"] = capabilities
    if cluster["channel"]:
        spec["channel"] = cluster["channel"]

    annotations = {}
    for key, annotation in OLM_CATALOG_ANNOTATIONS.items():
        if disconnected["olm_catalog_images"].get(key):
            annotations[annotation] = disconnected["olm_catalog_images"][key]
    if disconnected["olm_registry_overrides"]:
        annotations[OLM_REGISTRY_OVERRIDES_ANNOTATION] = disconnected["olm_registry_overrides"]

    metadata = {"name": cluster["name"], "namespace": cluster["namespace"], "labels": _labels(cluster)}
    if annotations:
        metadata["annotations"] = annotations
    return {"apiVersion": HYPERSHIFT_API, "kind": "HostedCluster", "metadata": metadata, "spec": spec}


def nodepool_manifest(cluster):
    """Render the default ``NodePool`` for a normalized definition."""
    pool = cluster["nodepool"]
    root = pool["root_volume"]
    persistent = {"size": root["size"]}
    if root["storage_class"]:
        persistent["storageClass"] = root["storage_class"]
    if root["access_mode"]:
        persistent["accessModes"] = [root["access_mode"]]
    if root["volume_mode"]:
        persistent["volumeMode"] = root["volume_mode"]
    root_volume = {"type": "Persistent", "persistent": persistent}
    if pool["cache_strategy"] == "PVC":
        root_volume["cacheStrategy"] = {"type": "PVC"}
    kubevirt = {
        "compute": {"cores": pool["cores"], "memory": pool["memory"], "qosClass": pool["qos_class"]},
        "rootVolume": root_volume,
        "networkInterfaceMultiqueue": pool["multiqueue"],
        "attachDefaultNetwork": pool["attach_default_network"],
    }
    if pool["additional_networks"]:
        kubevirt["additionalNetworks"] = [{"name": name} for name in pool["additional_networks"]]
    if pool["node_selector"]:
        kubevirt["nodeSelector"] = dict(pool["node_selector"])
    spec = {
        "clusterName": cluster["name"],
        "arch": pool["arch"],
        "release": {"image": cluster["release_image"]},
        "management": {"upgradeType": pool["upgrade_type"], "autoRepair": pool["auto_repair"]},
        "platform": {"type": "KubeVirt", "kubevirt": kubevirt},
    }
    if pool["autoscaling"]:
        spec["autoScaling"] = {"min": pool["autoscaling"]["min"], "max": pool["autoscaling"]["max"]}
    else:
        spec["replicas"] = pool["replicas"]
    return {
        "apiVersion": HYPERSHIFT_API,
        "kind": "NodePool",
        "metadata": {"name": pool["name"], "namespace": cluster["namespace"], "labels": _labels(cluster)},
        "spec": spec,
    }


def supporting_objects(cluster):
    """Names and labels of the namespaced objects ADO creates for a cluster."""
    labels = dict(_labels(cluster))
    secret_labels = dict(labels, **{SAFE_TO_DELETE_LABEL: "true"})
    out = {
        "labels": labels,
        "secret_labels": secret_labels,
        "pull_secret": cluster["pull_secret_name"] if cluster["pull_secret_source"] != "existing_secret" else "",
        "ssh_key_secret": cluster["ssh_key_secret_name"],
        "etcd_encryption_secret": cluster["etcd_encryption_secret_name"],
        "trust_bundle_configmap": cluster["trust_bundle_configmap_name"],
        "apps_service": f"{cluster['name']}-apps" if cluster["create_apps_load_balancer"] else "",
    }
    return out


def pull_secret_check(raw):
    """Validate dockerconfigjson content without returning it.

    ``raw`` may be a JSON string or an already-decoded dict. Returns
    ``{"valid": bool, "registries": [...], "error": str}``.
    """
    data = raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    if isinstance(raw, str):
        if not raw.strip():
            return {"valid": False, "registries": [], "error": "pull secret is empty"}
        try:
            data = json.loads(raw)
        except ValueError:
            return {"valid": False, "registries": [], "error": "pull secret is not valid JSON"}
    if not isinstance(data, dict) or not isinstance(data.get("auths"), dict) or not data["auths"]:
        return {"valid": False, "registries": [], "error": "pull secret has no 'auths' entries"}
    return {"valid": True, "registries": sorted(data["auths"].keys()), "error": ""}


# --------------------------------------------------------------------------
# support matrix
# --------------------------------------------------------------------------


def support_check(management_version, mce_version, hosted_version, matrix=None):
    """Check versions against the hosted control planes support matrix.

    ``matrix`` defaults to ``SUPPORT_MATRIX`` (OpenShift 4.22 docs); roles can
    pass a newer matrix with the same shape without code changes::

        {"mce": {"2.17": {"management": [...], "hosted": [...]}, ...},
         "kubevirt_platform": {"management": [...], "hosted": [...]}}
    """
    findings = []
    matrix = matrix or SUPPORT_MATRIX
    mgmt_minor = minor_version(management_version)
    mce_minor = minor_version(mce_version)
    hosted_minor = minor_version(hosted_version)
    mce_table = (matrix or {}).get("mce") or {}
    platform = (matrix or {}).get("kubevirt_platform") or {}

    def add(check_id, ok, message):
        findings.append({"id": check_id, "ok": bool(ok), "message": message})

    if not mce_minor:
        add("matrix.mce", False, "multicluster engine Operator version is unknown")
    elif mce_minor not in mce_table:
        add(
            "matrix.mce",
            False,
            f"multicluster engine Operator {mce_minor} is not in the support matrix "
            f"(known: {', '.join(sorted(mce_table, key=_version_tuple))})",
        )
    else:
        row = mce_table[mce_minor]
        add(
            "matrix.management",
            mgmt_minor in (row.get("management") or []),
            f"management cluster {mgmt_minor or 'unknown'} with multicluster engine Operator "
            f"{mce_minor} (supported management versions: {', '.join(row.get('management') or [])})",
        )
        if hosted_minor:
            add(
                "matrix.hosted",
                hosted_minor in (row.get("hosted") or []),
                f"hosted cluster {hosted_minor} with the HyperShift Operator in multicluster engine "
                f"Operator {mce_minor} (supported hosted versions: {', '.join(row.get('hosted') or [])})",
            )
    if platform:
        add(
            "matrix.kubevirt_management",
            mgmt_minor in (platform.get("management") or []),
            f"OpenShift Virtualization platform support for management cluster {mgmt_minor or 'unknown'}",
        )
        if hosted_minor:
            add(
                "matrix.kubevirt_hosted",
                hosted_minor in (platform.get("hosted") or []),
                f"OpenShift Virtualization platform support for hosted cluster {hosted_minor}",
            )
    return {"ok": all(item["ok"] for item in findings), "findings": findings}


# --------------------------------------------------------------------------
# fact shaping (raw k8s_info resources -> compact facts)
# --------------------------------------------------------------------------


def node_facts(nodes):
    """Summarize Node resources for capacity and topology checks."""
    out = []
    for node in nodes or []:
        meta = node.get("metadata") or {}
        labels = meta.get("labels") or {}
        status = node.get("status") or {}
        allocatable = status.get("allocatable") or {}
        out.append(
            {
                "name": meta.get("name", ""),
                "worker": "node-role.kubernetes.io/worker" in labels,
                "control_plane": "node-role.kubernetes.io/control-plane" in labels
                or "node-role.kubernetes.io/master" in labels,
                "ready": _condition(status.get("conditions"), "Ready") == "True",
                "schedulable": not bool((node.get("spec") or {}).get("unschedulable")),
                "cpu_allocatable_m": cpu_to_millicores(allocatable.get("cpu")),
                "memory_allocatable_b": quantity_to_bytes(allocatable.get("memory")) or 0,
                "pods_allocatable": _as_int(allocatable.get("pods"), 0) or 0,
                "zone": labels.get("topology.kubernetes.io/zone", ""),
            }
        )
    return out


def pod_requests(pods):
    """Sum CPU/memory requests and pod counts per node for non-terminal pods."""
    out = {}
    for pod in pods or []:
        status = pod.get("status") or {}
        if status.get("phase") in ("Succeeded", "Failed"):
            continue
        node = (pod.get("spec") or {}).get("nodeName")
        if not node:
            continue
        entry = out.setdefault(node, {"cpu_m": 0, "memory_b": 0, "pods": 0})
        entry["pods"] += 1
        containers = (pod.get("spec") or {}).get("containers") or []
        init = (pod.get("spec") or {}).get("initContainers") or []
        cpu = sum(
            cpu_to_millicores(((c.get("resources") or {}).get("requests") or {}).get("cpu"))
            for c in containers
        )
        mem = sum(
            quantity_to_bytes(((c.get("resources") or {}).get("requests") or {}).get("memory")) or 0
            for c in containers
        )
        # Effective request is the larger of the sum of app containers and any init container.
        for c in init:
            requests = (c.get("resources") or {}).get("requests") or {}
            cpu = max(cpu, cpu_to_millicores(requests.get("cpu")))
            mem = max(mem, quantity_to_bytes(requests.get("memory")) or 0)
        entry["cpu_m"] += cpu
        entry["memory_b"] += mem
    return out


def condition_status(conditions, ctype):
    """Return a condition status as True/False/None."""
    value = _condition(conditions, ctype)
    if value == "True":
        return True
    if value == "False":
        return False
    return None


def mce_facts(mce_resources):
    """Summarize the MultiClusterEngine resource."""
    items = mce_resources or []
    if not items:
        return {"present": False}
    mce = items[0]
    status = mce.get("status") or {}
    components = ((mce.get("spec") or {}).get("overrides") or {}).get("components") or []

    def enabled(name):
        for item in components:
            if item.get("name") == name:
                return _as_bool(item.get("enabled"), True)
        return None

    return {
        "present": True,
        "name": _get(mce, "metadata.name", ""),
        "version": _text(status.get("currentVersion")),
        "phase": _text(status.get("phase")),
        "hypershift_enabled": enabled("hypershift"),
        "hypershift_local_hosting_enabled": enabled("hypershift-local-hosting"),
    }


def cluster_operator_facts(resources):
    """``[{name, available, degraded}]`` from ClusterOperator resources."""
    out = []
    for item in resources or []:
        conditions = (item.get("status") or {}).get("conditions") or []
        out.append(
            {
                "name": _get(item, "metadata.name", ""),
                "available": condition_status(conditions, "Available"),
                "degraded": condition_status(conditions, "Degraded"),
            }
        )
    return out


def storage_class_facts(resources):
    """``[{name, provisioner, default, volume_binding_mode}]`` from StorageClasses."""
    out = []
    for item in resources or []:
        annotations = _get(item, "metadata.annotations", {}) or {}
        out.append(
            {
                "name": _get(item, "metadata.name", ""),
                "provisioner": _text(item.get("provisioner")),
                "default": _text(annotations.get("storageclass.kubernetes.io/is-default-class")).lower() == "true",
                "volume_binding_mode": _text(item.get("volumeBindingMode")),
            }
        )
    return out


def storage_profile_facts(resources):
    """``{class_name: [{access_modes, volume_mode}]}`` from CDI StorageProfiles."""
    out = {}
    for item in resources or []:
        sets = []
        for entry in _get(item, "status.claimPropertySets", []) or []:
            sets.append(
                {
                    "access_modes": list(entry.get("accessModes") or []),
                    "volume_mode": _text(entry.get("volumeMode")),
                }
            )
        out[_get(item, "metadata.name", "")] = sets
    return out


def snapshot_class_facts(resources):
    """``[{name, default}]`` from VolumeSnapshotClasses."""
    out = []
    for item in resources or []:
        annotations = _get(item, "metadata.annotations", {}) or {}
        out.append(
            {
                "name": _get(item, "metadata.name", ""),
                "default": _text(annotations.get("snapshot.storage.kubernetes.io/is-default-class")).lower() == "true",
            }
        )
    return out


def install_config_fips(raw):
    """FIPS flag from the kube-system/cluster-config-v1 install-config text.

    Returns True/False, or None when the text is missing or unreadable. Uses a
    line match so no YAML loader is needed for this single key.
    """
    text = _text(raw)
    if not text:
        return None
    match = re.search(r"(?m)^fips:\s*(\S+)\s*$", text)
    if not match:
        return False
    return _as_bool(match.group(1))


def access_reviews(clusters, existing_namespaces=None, wildcard_planned=False, install_planned=None):
    """SelfSubjectAccessReview resourceAttributes needed to deploy ``clusters``.

    Returns ``[{"key": str, "attributes": {...}}]``; keys are unique and human
    readable so the report can name a missing permission.
    """
    present = set(existing_namespaces or [])
    reviews = {}

    def add(verb, resource, group="", namespace="", name=""):
        attributes = {"verb": verb, "resource": resource}
        if group:
            attributes["group"] = group
        if namespace:
            attributes["namespace"] = namespace
        if name:
            attributes["name"] = name
        scope = f" in {namespace}" if namespace else " (cluster scope)"
        key = f"{verb} {resource}{'.' + group if group else ''}{'/' + name if name else ''}{scope}"
        reviews[key] = attributes

    for cluster in clusters or []:
        namespace = cluster["namespace"]
        if namespace not in present:
            add("create", "namespaces")
        for resource in ("hostedclusters", "nodepools"):
            add("create", resource, "hypershift.openshift.io", namespace)
            add("get", resource, "hypershift.openshift.io", namespace)
        add("create", "secrets", namespace=namespace)
        add("get", "secrets", namespace=namespace)
        if cluster["trust_bundle_configmap_name"]:
            add("create", "configmaps", namespace=namespace)
        if cluster["pull_secret_source"] == "management_cluster":
            add("get", "secrets", namespace="openshift-config", name="pull-secret")
        if cluster["create_apps_load_balancer"]:
            add("create", "services", namespace=cluster["hcp_namespace"])
    if wildcard_planned:
        add("patch", "ingresscontrollers", "operator.openshift.io", "openshift-ingress-operator", "default")
    planned = [item for item in _split_list(install_planned) if item in INSTALLABLE]
    if planned:
        add("get", "packagemanifests", "packages.operators.coreos.com", "openshift-marketplace")
    for item in planned:
        namespace = INSTALLABLE[item]["namespace"]
        if namespace not in present:
            add("create", "namespaces")
        add("create", "operatorgroups", "operators.coreos.com", namespace)
        add("create", "subscriptions", "operators.coreos.com", namespace)
    if "mce" in planned:
        add("create", "multiclusterengines", "multicluster.openshift.io")
    if "virtualization" in planned:
        add("create", "hyperconvergeds", "hco.kubevirt.io", "openshift-cnv")
    if "metallb" in planned:
        for resource in ("metallbs", "ipaddresspools", "l2advertisements"):
            add("create", resource, "metallb.io", "metallb-system")
    return [{"key": key, "attributes": attrs} for key, attrs in sorted(reviews.items())]


def package_facts(packagemanifest):
    """Catalog source, default channel, and channels of an OLM PackageManifest."""
    pm = packagemanifest or {}
    status = pm.get("status") or {}
    channels = [_text(item.get("name")) for item in status.get("channels") or [] if item.get("name")]
    return {
        "present": bool(pm),
        "name": _get(pm, "metadata.name", "") or "",
        "catalog_source": _text(status.get("catalogSource")),
        "catalog_source_namespace": _text(status.get("catalogSourceNamespace")),
        "default_channel": _text(status.get("defaultChannel")),
        "channels": channels,
    }


PREFERRED_CATALOG = "redhat-operators"


def package_options(value):
    """``package_facts`` for each catalog that serves a package.

    ``value`` is one PackageManifest, a list of them (one per catalog source,
    as listed by name), or ``package_facts`` output. Catalogs that do not
    serve the package are dropped.
    """
    items = value if isinstance(value, list) else [value]
    options = []
    for item in items:
        facts = item if isinstance(item, dict) and "channels" in item else package_facts(item)
        if facts.get("present"):
            options.append(facts)
    return options


def preferred_package(value):
    """The catalog to subscribe from: redhat-operators when it serves the package."""
    options = [o for o in package_options(value) if o.get("default_channel")]
    for option in options:
        if option.get("catalog_source") == PREFERRED_CATALOG:
            return option
    return options[0] if options else package_facts({})


def mce_channel(package, management_version, hosted_versions=None, matrix=None):
    """Pick the multicluster engine Operator channel and catalog to install from.

    ``package`` is a PackageManifest, a list of them (several catalog sources
    can serve multicluster-engine), or ``package_facts`` output. Chooses the
    newest ``stable-X.Y`` channel, in any catalog, whose support matrix row
    lists the management cluster version and every requested hosted version;
    redhat-operators wins a tie.
    """
    options = package_options(package)
    table = (matrix or SUPPORT_MATRIX).get("mce") or {}
    mgmt = minor_version(management_version)
    hosted = sorted({minor_version(v) for v in hosted_versions or [] if minor_version(v)}, key=_version_tuple)
    result = {"ok": False, "channel": "", "version": "", "catalog_source": "", "catalog_source_namespace": ""}
    if not options:
        result["message"] = "package multicluster-engine is not available from any catalog source"
        return result
    best = None
    for option in options:
        for channel in option.get("channels") or []:
            match = re.fullmatch(r"stable-(\d+\.\d+)", channel)
            row = table.get(match.group(1)) if match else None
            if not row:
                continue
            if mgmt and mgmt not in row.get("management", []):
                continue
            if any(item not in row.get("hosted", []) for item in hosted):
                continue
            rank = (_version_tuple(match.group(1)), option.get("catalog_source") == PREFERRED_CATALOG)
            if best is None or rank > best[0]:
                best = (rank, match.group(1), option)
    if best is None:
        offered = "; ".join(
            f"{o.get('catalog_source') or 'unknown'}: {', '.join(o.get('channels') or []) or 'none'}" for o in options
        )
        result["message"] = (
            f"no multicluster-engine channel supports management cluster {mgmt or 'unknown'} with hosted "
            f"{', '.join(hosted) or 'unknown'} (catalogs: {offered})"
        )
        return result
    _rank, version, option = best
    result.update(
        ok=True,
        channel=f"stable-{version}",
        version=version,
        catalog_source=option.get("catalog_source", ""),
        catalog_source_namespace=option.get("catalog_source_namespace", ""),
        message=f"multicluster engine Operator {version} (channel stable-{version} from {option.get('catalog_source')})",
    )
    return result


def resource_refs(resources):
    """``[{name, namespace}]`` for a list of resources."""
    return [
        {"name": _get(item, "metadata.name", ""), "namespace": _get(item, "metadata.namespace", "")}
        for item in resources or []
    ]


def mirror_sources(idms=None, icsp=None):
    """Collect mirrored source repositories from IDMS and ICSP resources."""
    sources = set()
    for item in idms or []:
        for entry in (item.get("spec") or {}).get("imageDigestMirrors") or []:
            if entry.get("source") and entry.get("mirrors"):
                sources.add(entry["source"])
    for item in icsp or []:
        for entry in (item.get("spec") or {}).get("repositoryDigestMirrors") or []:
            if entry.get("source") and entry.get("mirrors"):
                sources.add(entry["source"])
    return sorted(sources)


# --------------------------------------------------------------------------
# prerequisite evaluation
# --------------------------------------------------------------------------


class _Report:
    def __init__(self):
        self.checks = []

    def add(self, check_id, category, severity, status, message, remediation="", cluster=""):
        self.checks.append(
            {
                "id": check_id,
                "category": category,
                "severity": severity,
                "status": status,
                "cluster": cluster,
                "message": message,
                "remediation": remediation,
            }
        )

    def require(self, check_id, category, ok, message, remediation="", cluster=""):
        self.add(check_id, category, "required", "pass" if ok else "fail", message, remediation, cluster)

    def recommend(self, check_id, category, ok, message, remediation="", cluster=""):
        self.add(check_id, category, "recommended", "pass" if ok else "warn", message, remediation, cluster)

    def info(self, check_id, category, message, cluster=""):
        self.add(check_id, category, "info", "info", message, "", cluster)

    def planned(self, check_id, category, message, cluster=""):
        """Required item that is missing now and installed by the deploy run."""
        self.add(check_id, category, "required", "planned", message, "", cluster)

    def result(self):
        missing = [c for c in self.checks if c["severity"] == "required" and c["status"] == "fail"]
        optimizations = [c for c in self.checks if c["severity"] == "recommended" and c["status"] == "warn"]
        passed = [c for c in self.checks if c["status"] == "pass"]
        planned = [c for c in self.checks if c["status"] == "planned"]
        return {
            "ready": not missing,
            "checks": self.checks,
            "missing": missing,
            "optimizations": optimizations,
            "planned": planned,
            "summary": {
                "planned": len(planned),
                "required_failed": len(missing),
                "recommended_warnings": len(optimizations),
                "passed": len(passed),
                "total": len(self.checks),
            },
        }


def _condition(conditions, ctype):
    for item in conditions or []:
        if item.get("type") == ctype:
            return _text(item.get("status"))
    return ""


def _sc_by_name(facts, name):
    for item in facts.get("storage_classes") or []:
        if item.get("name") == name:
            return item
    return None


def _default_sc(facts):
    for item in facts.get("storage_classes") or []:
        if item.get("default"):
            return item
    return None


def _sc_supports_rwx(facts, name):
    """True/False from the CDI StorageProfile, None when unknown."""
    profiles = facts.get("storage_profiles") or {}
    if name not in profiles:
        return None
    sets = profiles.get(name) or []
    if not sets:
        return None
    return any("ReadWriteMany" in (item.get("access_modes") or []) for item in sets)


def _capacity(facts, clusters, sizing):
    """Return (ok, message) for worker capacity versus requested hosted clusters."""
    workers = [
        node for node in (facts.get("nodes") or [])
        if node.get("worker") and node.get("ready") and node.get("schedulable", True)
    ]
    requests = facts.get("pod_requests") or {}
    free_cpu = 0
    free_mem = 0
    for node in workers:
        used = requests.get(node.get("name"), {})
        free_cpu += max(0, int(node.get("cpu_allocatable_m") or 0) - int(used.get("cpu_m") or 0))
        free_mem += max(0, int(node.get("memory_allocatable_b") or 0) - int(used.get("memory_b") or 0))
    need_cpu = 0
    need_mem = 0
    for cluster in clusters:
        if cluster.get("_exists"):
            continue
        pool = cluster["nodepool"]
        count = pool["replicas"] if pool["replicas"] is not None else (pool.get("autoscaling") or {}).get("min", 0)
        cp_cpu = cpu_to_millicores(sizing.get("control_plane_cpu", "5"))
        cp_mem = quantity_to_bytes(sizing.get("control_plane_memory", "18Gi")) or 0
        need_cpu += cp_cpu + count * pool["cores"] * 1000
        need_mem += cp_mem + count * (quantity_to_bytes(pool["memory"]) or 0)
    gib = 1024 ** 3
    message = (
        f"free worker capacity {free_cpu / 1000:.1f} vCPU / {free_mem / gib:.1f} GiB; "
        f"requested {need_cpu / 1000:.1f} vCPU / {need_mem / gib:.1f} GiB "
        f"(control plane baseline {sizing.get('control_plane_cpu', '5')} vCPU / "
        f"{sizing.get('control_plane_memory', '18Gi')} per hosted cluster plus worker VMs; "
        "excludes virt-launcher overhead)"
    )
    return (free_cpu >= need_cpu and free_mem >= need_mem), message


def prereq_report(facts, clusters, settings=None, matrix=None):
    """Evaluate management cluster prerequisites for KubeVirt hosted clusters.

    ``facts`` is the dict built by ``ocp_hcp_kubevirt_prereqs`` from read-only
    API calls. ``clusters`` are normalized definitions (``normalize_cluster``).
    Clusters that already exist may carry ``_exists: true`` so capacity and
    name checks skip them.

    Required failures block deployment; recommended warnings are optional
    optimizations; info entries are context.
    """
    facts = facts or {}
    settings = settings or {}
    rep = _Report()
    existing_keys = {
        (item.get("name"), item.get("namespace")) for item in facts.get("existing_hostedclusters") or []
    }
    clusters = [
        dict(item, _exists=bool(item.get("_exists")) or (item["name"], item["namespace"]) in existing_keys)
        for item in clusters or []
    ]
    # Prerequisites the deploy run installs when they are missing
    # (install_prerequisites). Each needs its OLM package in a catalog source.
    install_planned = {item for item in _split_list(settings.get("install_planned")) if item in INSTALLABLE}
    packages = facts.get("packages") or {}
    new_hosted_versions = [c["hosted_version"] for c in clusters if not c.get("_exists")]

    # ----- management cluster -----
    cv = facts.get("clusterversion") or {}
    mgmt_version = _text(cv.get("version"))
    rep.require(
        "management.version",
        "management_cluster",
        bool(mgmt_version),
        f"management cluster version: {mgmt_version or 'unknown'}",
        "Ensure the automation identity can read clusterversions.config.openshift.io.",
    )
    rep.require(
        "management.available",
        "management_cluster",
        cv.get("available") is True and cv.get("failing") is not True,
        f"ClusterVersion Available={cv.get('available')} Failing={cv.get('failing')}",
        "Resolve ClusterVersion failures before deploying hosted control planes.",
    )
    rep.recommend(
        "management.not_updating",
        "management_cluster",
        cv.get("progressing") is not True,
        "management cluster is not in the middle of an update"
        if cv.get("progressing") is not True
        else "management cluster update in progress",
        "Wait for the management cluster update to finish (update order: management cluster, "
        "then multicluster engine Operator, then hosted clusters).",
    )
    bad_operators = [
        op.get("name")
        for op in facts.get("clusteroperators") or []
        if op.get("available") is not True or op.get("degraded") is True
    ]
    rep.require(
        "management.cluster_operators",
        "management_cluster",
        not bad_operators,
        "all cluster operators are Available and not Degraded"
        if not bad_operators
        else f"unhealthy cluster operators: {', '.join(sorted(bad_operators))}",
        "Fix degraded or unavailable cluster operators (oc get co).",
    )
    infra = facts.get("infrastructure") or {}
    platform = _text(infra.get("platform"))
    if platform == "BareMetal":
        rep.require("management.platform", "management_cluster", True, "management cluster platform: BareMetal")
    elif platform == "None":
        rep.recommend(
            "management.platform",
            "management_cluster",
            False,
            "management cluster platform is None; the docs require an on-premise bare metal "
            "management cluster for the KubeVirt platform",
            "Confirm the management cluster runs on bare metal hardware.",
        )
    else:
        allowed = _as_bool(settings.get("allow_unsupported_platform"))
        message = (
            f"management cluster platform '{platform or 'unknown'}' is not on-premise bare metal "
            "(OpenShift 4.22 docs: 'The management cluster is on-premise bare metal')"
        )
        if allowed:
            rep.recommend(
                "management.platform",
                "management_cluster",
                False,
                "UNSUPPORTED: " + message + " (override set)",
                "Use a bare metal management cluster for supported deployments.",
            )
        else:
            rep.require(
                "management.platform",
                "management_cluster",
                False,
                message,
                "Use a bare metal management cluster. Labs can set allow_unsupported_platform, "
                "which is not a supported configuration.",
            )
    single_node = _text(infra.get("control_plane_topology")) == "SingleReplica"
    rep.require(
        "management.not_sno",
        "management_cluster",
        not single_node,
        "management cluster is not single-node OpenShift"
        if not single_node
        else "single-node OpenShift is not supported as a management cluster",
        "Use a cluster with at least three worker nodes.",
    )
    workers = [n for n in facts.get("nodes") or [] if n.get("worker") and n.get("ready")]
    min_workers = int(settings.get("min_workers", 3))
    rep.require(
        "management.workers",
        "management_cluster",
        len(workers) >= min_workers,
        f"{len(workers)} Ready worker nodes (HyperShift needs at least {min_workers})",
        "Add worker nodes; the HyperShift Operator needs at least three.",
    )
    zones = {n.get("zone") for n in workers if n.get("zone")}
    if any(c["controller_availability_policy"] == "HighlyAvailable" for c in clusters):
        rep.recommend(
            "management.zones",
            "management_cluster",
            len(zones) >= 3,
            f"{len(zones)} distinct topology.kubernetes.io/zone values on Ready workers",
            "Label management cluster nodes with topology.kubernetes.io/zone so highly available "
            "control plane pods spread across failure domains.",
        )
    if settings.get("check_capacity", True):
        ok, message = _capacity(facts, clusters, settings.get("sizing") or {})
        rep.require(
            "management.capacity",
            "management_cluster",
            ok,
            message,
            "Add worker capacity or reduce worker VM count, cores, or memory.",
        )
    pod_limited = [
        n.get("name")
        for n in workers
        if int(n.get("pods_allocatable") or 0)
        and int((facts.get("pod_requests") or {}).get(n.get("name"), {}).get("pods") or 0)
        + int(settings.get("control_plane_pods", 78))
        > int(n.get("pods_allocatable") or 0)
    ]
    rep.recommend(
        "management.max_pods",
        "management_cluster",
        not pod_limited,
        "worker maxPods leaves room for a hosted control plane (~78 pods each)"
        if not pod_limited
        else f"workers near maxPods: {', '.join(sorted(pod_limited))}",
        "Raise maxPods with a KubeletConfig (the sizing guide suggests 500) for control plane density.",
    )

    # ----- networking -----
    network = facts.get("network") or {}
    rep.require(
        "network.ovn",
        "networking",
        network.get("type") == "OVNKubernetes",
        f"management cluster network type: {network.get('type') or 'unknown'}",
        "The KubeVirt platform requires OVN-Kubernetes as the default CNI.",
    )
    mtu = int(network.get("mtu") or 0)
    rep.recommend(
        "network.mtu",
        "networking",
        mtu >= 9000,
        f"cluster network MTU {mtu or 'unknown'} (9000 or greater recommended for KubeVirt workers)",
        "MTU cannot change after installation; expect lower hosted pod throughput below 9000.",
    )
    if mtu and mtu < 9000:
        multiqueue_on = [c["name"] for c in clusters if c["nodepool"]["multiqueue"] == "Enable"]
        rep.recommend(
            "network.multiqueue",
            "networking",
            not multiqueue_on,
            "network multiqueue disabled for MTU below 9000"
            if not multiqueue_on
            else f"network multiqueue is Enable with MTU {mtu} for: {', '.join(multiqueue_on)}",
            "The docs advise enabling multiqueue only when the MTU is 9000 or greater; "
            "set network_multiqueue to Disable.",
        )

    # ----- multicluster engine / HyperShift -----
    crds = facts.get("crds") or {}
    mce = facts.get("mce") or {}
    mce_plan = {}
    if not mce.get("present") and "mce" in install_planned:
        mce_plan = mce_channel(packages.get("mce") or [], mgmt_version, new_hosted_versions, matrix)
        if mce_plan["ok"]:
            rep.planned(
                "mce.installed",
                "hosted_control_planes",
                f"multicluster engine Operator not found; deploy installs {mce_plan['message']}",
            )
        else:
            rep.require(
                "mce.installed",
                "hosted_control_planes",
                False,
                f"multicluster engine Operator not found and cannot be installed: {mce_plan['message']}",
                "Make the multicluster-engine package available from a catalog source (mirror it when "
                "disconnected), or install the multicluster engine Operator yourself.",
            )
    else:
        rep.require(
            "mce.installed",
            "hosted_control_planes",
            bool(mce.get("present")),
            f"multicluster engine Operator: {mce.get('version') or 'not found'}",
            "Turn on install_prerequisites (Preflight: Set up missing prerequisites), install the "
            "multicluster engine Operator, or install ACM, which includes it (ADO's acm component).",
        )
    mce_planned = bool(mce_plan.get("ok"))
    if mce.get("present"):
        rep.require(
            "mce.available",
            "hosted_control_planes",
            mce.get("phase") == "Available",
            f"MultiClusterEngine phase: {mce.get('phase') or 'unknown'}",
            "Wait for the MultiClusterEngine resource to report Available.",
        )
        rep.require(
            "mce.hypershift_enabled",
            "hosted_control_planes",
            mce.get("hypershift_enabled") is not False,
            "hosted control planes component (hypershift) "
            + ("disabled" if mce.get("hypershift_enabled") is False else "enabled")
            + " in MultiClusterEngine",
            "oc patch mce multiclusterengine --type=merge -p "
            "'{\"spec\":{\"overrides\":{\"components\":[{\"name\":\"hypershift\",\"enabled\":true}]}}}'",
        )
        rep.require(
            "mce.hypershift_local_hosting",
            "hosted_control_planes",
            mce.get("hypershift_local_hosting_enabled") is not False,
            "hypershift-local-hosting component "
            + ("disabled" if mce.get("hypershift_local_hosting_enabled") is False else "enabled")
            + " in MultiClusterEngine",
            "Enable the hypershift-local-hosting component in the MultiClusterEngine resource.",
        )
    operator = facts.get("hypershift_operator") or {}
    if mce_planned:
        rep.planned(
            "hypershift.operator",
            "hosted_control_planes",
            "HyperShift Operator and the HostedCluster/NodePool APIs come with the multicluster engine Operator",
        )
    else:
        rep.require(
            "hypershift.operator",
            "hosted_control_planes",
            operator.get("available") is True,
            "HyperShift Operator deployment Available in namespace hypershift"
            if operator.get("available")
            else "HyperShift Operator is not running in namespace hypershift",
            "Confirm the hypershift-addon is installed on local-cluster (oc get managedclusteraddons "
            "-n local-cluster hypershift-addon).",
        )
        rep.require(
            "hypershift.crds",
            "hosted_control_planes",
            bool(crds.get("hostedclusters")) and bool(crds.get("nodepools")),
            "HostedCluster and NodePool APIs (hypershift.openshift.io/v1beta1) "
            + ("are served" if crds.get("hostedclusters") and crds.get("nodepools") else "are not served"),
            "The HyperShift Operator installs these CRDs.",
        )
    local_cluster = facts.get("local_cluster") or {}
    if crds.get("managedclusters"):
        rep.require(
            "mce.local_cluster",
            "hosted_control_planes",
            bool(local_cluster.get("present")),
            "local-cluster ManagedCluster exists" if local_cluster.get("present") else "local-cluster ManagedCluster not found",
            "multicluster engine Operator must manage at least local-cluster (oc get managedclusters local-cluster).",
        )
    addon = facts.get("hypershift_addon") or {}
    if addon.get("checked"):
        rep.require(
            "mce.hypershift_addon",
            "hosted_control_planes",
            addon.get("available") is True,
            f"hypershift-addon ManagedClusterAddOn Available={addon.get('available')}",
            "Create or repair the hypershift-addon ManagedClusterAddOn in namespace local-cluster.",
        )
    supported = [minor_version(v) for v in facts.get("supported_versions") or [] if minor_version(v)]
    rep.info(
        "hypershift.supported_versions",
        "hosted_control_planes",
        f"HyperShift supported-versions: {', '.join(supported) or 'unknown'}",
    )
    rep.info(
        "tools.hcp_cli",
        "access",
        "ADO uses the hypershift.openshift.io API directly; the hcp CLI is optional "
        f"(ConsoleCLIDownload hcp-cli-download {'present' if facts.get('hcp_cli_download') else 'not found'})",
    )

    # ----- OpenShift Virtualization -----
    cnv = facts.get("cnv") or {}
    virt_pkg = preferred_package(packages.get("virtualization") or [])
    virt_planned = (
        not cnv.get("present") and "virtualization" in install_planned
        and bool(virt_pkg.get("present")) and bool(virt_pkg.get("default_channel"))
    )
    if virt_planned:
        rep.planned(
            "virt.installed",
            "openshift_virtualization",
            "OpenShift Virtualization not found; deploy installs it (channel "
            f"{virt_pkg['default_channel']} from {virt_pkg.get('catalog_source') or 'unknown'})",
        )
        rep.planned(
            "virt.apis",
            "openshift_virtualization",
            "KubeVirt and CDI APIs come with OpenShift Virtualization",
        )
    else:
        if not cnv.get("present") and "virtualization" in install_planned:
            message = (
                "OpenShift Virtualization not found and cannot be installed: package kubevirt-hyperconverged "
                "is not available from any catalog source"
            )
        else:
            message = f"OpenShift Virtualization: {cnv.get('version') or 'not found'}"
        rep.require(
            "virt.installed",
            "openshift_virtualization",
            bool(cnv.get("present")),
            message,
            "Turn on install_prerequisites (Preflight: Set up missing prerequisites), or install OpenShift "
            "Virtualization 4.14 or later (ADO's OpenShift Virtualization component). Mirror the "
            "kubevirt-hyperconverged package when disconnected.",
        )
        if cnv.get("present"):
            rep.require(
                "virt.healthy",
                "openshift_virtualization",
                cnv.get("available") is True and cnv.get("degraded") is not True,
                f"HyperConverged Available={cnv.get('available')} Degraded={cnv.get('degraded')}",
                "Fix the HyperConverged resource in openshift-cnv.",
            )
            cnv_version = parse_version(cnv.get("version"))
            rep.require(
                "virt.version",
                "openshift_virtualization",
                bool(cnv_version) and version_compare(cnv_version, "4.14") >= 0,
                f"OpenShift Virtualization version {cnv_version or 'unknown'} (4.14 or later required)",
                "Update OpenShift Virtualization.",
            )
        rep.require(
            "virt.apis",
            "openshift_virtualization",
            bool(crds.get("kubevirt")) and bool(crds.get("cdi")),
            "KubeVirt and CDI APIs " + ("are served" if crds.get("kubevirt") and crds.get("cdi") else "are not served"),
            "OpenShift Virtualization provides kubevirt.io and cdi.kubevirt.io.",
        )

    # ----- storage -----
    default_sc = _default_sc(facts)
    rep.require(
        "storage.default_class",
        "storage",
        default_sc is not None,
        f"default StorageClass: {default_sc.get('name') if default_sc else 'none'}",
        "Mark a StorageClass as default (storageclass.kubernetes.io/is-default-class=true).",
    )
    rep.recommend(
        "storage.default_snapshot_class",
        "storage",
        any(item.get("default") for item in facts.get("volume_snapshot_classes") or []),
        "default VolumeSnapshotClass "
        + ("present" if any(item.get("default") for item in facts.get("volume_snapshot_classes") or []) else "not set"),
        "Without class mappings, hosted clusters use the default StorageClass and VolumeSnapshotClass; "
        "set a default VolumeSnapshotClass for hosted snapshots.",
    )

    # ----- ingress, DNS, load balancing -----
    ingress = facts.get("ingress") or {}
    passthrough = [c["name"] for c in clusters if c["base_domain_passthrough"] and not c.get("_exists")]
    if passthrough:
        wildcard_ok = ingress.get("wildcard_policy") == "WildcardsAllowed"
        planned = _as_bool(settings.get("wildcard_remediation_planned"))
        if wildcard_ok or not planned:
            rep.require(
                "ingress.wildcard_routes",
                "ingress_dns",
                wildcard_ok,
                "default IngressController allows wildcard routes"
                if wildcard_ok
                else "default IngressController does not allow wildcard routes (needed for the default "
                f"hosted ingress of: {', '.join(passthrough)})",
                "Enable 'Allow wildcard route admission' in Preflight (explicit opt-in) or run: "
                "oc patch ingresscontroller -n openshift-ingress-operator default --type=json -p "
                "'[{\"op\":\"add\",\"path\":\"/spec/routeAdmission\",\"value\":{\"wildcardPolicy\":\"WildcardsAllowed\"}}]'",
            )
        else:
            rep.recommend(
                "ingress.wildcard_routes",
                "ingress_dns",
                False,
                "wildcard route admission is not enabled yet; the deploy run will enable it (opt-in selected)",
            )
        apps_domain = _text(ingress.get("default_domain"))
        for name in passthrough:
            rep.info(
                "ingress.default_domain",
                "ingress_dns",
                f"{name}: default hosted ingress *.apps.{name}.{apps_domain or '<management apps domain>'} "
                "(HTTPS on 443 only)",
                cluster=name,
            )
    lb_users = [c["name"] for c in clusters if c["api_publishing"] == "LoadBalancer" and not c.get("_exists")]
    custom_domain = [c["name"] for c in clusters if c["create_apps_load_balancer"] and not c.get("_exists")]
    metallb = facts.get("metallb") or {}
    metallb_ready = (
        bool(metallb.get("instance_present")) and int(metallb.get("pools") or 0) > 0
        and int(metallb.get("advertisements") or 0) > 0
    )
    metallb_pools = _split_list(settings.get("metallb_address_pools"))
    metallb_pkg = preferred_package(packages.get("metallb") or [])
    lb_needed = (lb_users or custom_domain) and settings.get("load_balancer_check", "metallb") == "metallb"
    if lb_needed and not metallb_ready and "metallb" in install_planned:
        if metallb_pools and (metallb.get("instance_present") or metallb_pkg.get("present")):
            rep.planned(
                "ingress.load_balancer",
                "ingress_dns",
                f"MetalLB is not fully set up; deploy configures it with address pool {', '.join(metallb_pools)}",
            )
        else:
            rep.require(
                "ingress.load_balancer",
                "ingress_dns",
                False,
                "MetalLB is not set up and cannot be configured: "
                + ("no MetalLB address pool was given" if not metallb_pools
                   else "package metallb-operator is not available from any catalog source"),
                "Enter a MetalLB address range from your network (Preflight: MetalLB address pool), or "
                "publish the API with NodePort.",
            )
    elif lb_needed:
        rep.require(
            "ingress.load_balancer",
            "ingress_dns",
            bool(metallb.get("instance_present")) and int(metallb.get("pools") or 0) > 0
            and int(metallb.get("advertisements") or 0) > 0,
            f"MetalLB instance={bool(metallb.get('instance_present'))} IPAddressPools={metallb.get('pools') or 0} "
            f"advertisements={metallb.get('advertisements') or 0}",
            "Configure MetalLB (MetalLB resource, IPAddressPool, L2Advertisement) before creating hosted "
            "clusters (the ocp_metallb_install role can do this), or publish the API with NodePort.",
        )
    for cluster in clusters:
        if cluster.get("_exists"):
            continue
        if cluster["base_domain"]:
            rep.info(
                "ingress.custom_dns",
                "ingress_dns",
                f"{cluster['name']}: create DNS records api.{cluster['name']}.{cluster['base_domain']} -> API "
                f"load balancer IP and *.apps.{cluster['name']}.{cluster['base_domain']} -> the "
                f"{cluster['name']}-apps load balancer IP after creation",
                cluster=cluster["name"],
            )

    # ----- access, pull secret, release image -----
    access = facts.get("access") or {}
    denied = sorted(key for key, allowed in access.items() if allowed is False)
    rep.require(
        "access.permissions",
        "access",
        not denied,
        "automation identity has the required permissions"
        if not denied
        else f"automation identity is missing permissions: {', '.join(denied)}",
        "Grant the permissions listed in docs/SHIFT_ON_SHIFT.md (least-privilege ClusterRole example).",
    )
    pull = facts.get("pull_secrets") or {}
    existing = facts.get("existing_hostedclusters") or []
    managed = set(facts.get("managed_clusters") or [])
    idms_sources = set(facts.get("mirror_sources") or [])
    for cluster in clusters:
        name = cluster["name"]
        state = pull.get(name) or {}
        rep.require(
            "pull_secret.valid",
            "access",
            state.get("valid") is True,
            f"{name}: pull secret ({cluster['pull_secret_source']}) "
            + ("is valid" if state.get("valid") else (state.get("error") or "not checked")),
            "Provide a pull secret with auths for quay.io/openshift-release-dev (or your mirror registry).",
            cluster=name,
        )
        if cluster.get("_exists"):
            rep.info("cluster.exists", "hosted_cluster", f"{name}: HostedCluster already exists; it will not be recreated", cluster=name)
            continue
        clash = [item for item in existing if item.get("name") == name and item.get("namespace") != cluster["namespace"]]
        rep.require(
            "cluster.unique_name",
            "hosted_cluster",
            not clash and name not in managed,
            f"{name}: name is unique among hosted and managed clusters"
            if not clash and name not in managed
            else f"{name}: a hosted or managed cluster with this name already exists",
            "Hosted cluster names must be unique across the hub.",
            cluster=name,
        )
        rep.require(
            "cluster.namespace_not_managed",
            "hosted_cluster",
            cluster["namespace"] not in managed,
            f"{name}: namespace {cluster['namespace']} "
            + ("is a managed cluster namespace" if cluster["namespace"] in managed else "is not a managed cluster namespace"),
            "Do not create a hosted cluster in the namespace of a managed cluster.",
            cluster=name,
        )
        hosted_minor = cluster["hosted_minor"]
        if supported:
            rep.require(
                "release.supported_version",
                "release",
                hosted_minor in supported,
                f"{name}: hosted version {hosted_minor or 'unknown'} "
                + ("is" if hosted_minor in supported else "is not")
                + f" in the HyperShift supported-versions list ({', '.join(supported)})",
                "Update the multicluster engine Operator to a release whose HyperShift Operator supports "
                "this OpenShift version, or pick a supported release image.",
                cluster=name,
            )
        check = support_check(
            mgmt_version, mce.get("version") or mce_plan.get("version"), cluster["hosted_version"], matrix
        )
        for finding in check["findings"]:
            rep.require(
                finding["id"],
                "support_matrix",
                finding["ok"],
                f"{name}: {finding['message']}",
                "See the OpenShift 4.22 'Support matrix for hosted control planes'.",
                cluster=name,
            )
        rep.info(
            "release.image",
            "release",
            f"{name}: release image {cluster['release_image']} (pullability is confirmed after creation "
            "by the HostedCluster ValidReleaseImage condition)",
            cluster=name,
        )
        if cluster["fips"]:
            rep.require(
                "cluster.fips",
                "hosted_cluster",
                facts.get("fips_enabled") is True,
                f"{name}: FIPS hosted cluster needs a FIPS-enabled management cluster "
                f"(management FIPS={facts.get('fips_enabled')})",
                "Deploy FIPS hosted clusters only from a FIPS-enabled management cluster.",
                cluster=name,
            )
        # storage per cluster
        for label, sc_name in (
            ("etcd", cluster["etcd"]["storage_class"]),
            ("root volume", cluster["nodepool"]["root_volume"]["storage_class"]),
        ):
            if sc_name:
                rep.require(
                    f"storage.{label.replace(' ', '_')}_class",
                    "storage",
                    _sc_by_name(facts, sc_name) is not None,
                    f"{name}: {label} StorageClass {sc_name} "
                    + ("exists" if _sc_by_name(facts, sc_name) is not None else "not found"),
                    f"Create StorageClass {sc_name} or choose an existing one.",
                    cluster=name,
                )
        etcd_sc = _sc_by_name(facts, cluster["etcd"]["storage_class"]) if cluster["etcd"]["storage_class"] else default_sc
        rep.recommend(
            "storage.etcd_low_latency",
            "storage",
            bool(etcd_sc) and "topolvm" in _text(etcd_sc.get("provisioner")),
            f"{name}: etcd StorageClass {etcd_sc.get('name') if etcd_sc else 'unknown'} "
            f"(provisioner {etcd_sc.get('provisioner') if etcd_sc else 'unknown'})",
            "The docs recommend fast dedicated storage for hosted etcd, for example an LVM Storage class.",
            cluster=name,
        )
        root_sc_name = cluster["nodepool"]["root_volume"]["storage_class"] or (default_sc or {}).get("name", "")
        rwx = _sc_supports_rwx(facts, root_sc_name) if root_sc_name else None
        if cluster["require_live_migration"] and rwx is None and virt_planned:
            rep.recommend(
                "storage.live_migration",
                "storage",
                False,
                f"{name}: ReadWriteMany support of root volume StorageClass {root_sc_name or 'unknown'} is "
                "checked after OpenShift Virtualization is installed (deploy validates again)",
                cluster=name,
            )
        elif cluster["require_live_migration"]:
            rep.require(
                "storage.live_migration",
                "storage",
                rwx is True,
                f"{name}: root volume StorageClass {root_sc_name or 'unknown'} ReadWriteMany support "
                f"for live migration (CDI StorageProfile): {'yes' if rwx else 'no' if rwx is False else 'unknown'}",
                "Live migration needs RWX storage for the root volume and kubevirt-csi mapped classes.",
                cluster=name,
            )
        else:
            rep.recommend(
                "storage.live_migration",
                "storage",
                rwx is True,
                f"{name}: worker VMs live-migratable during management cluster maintenance: "
                f"{'yes' if rwx else 'no' if rwx is False else 'unknown'} (root volume class {root_sc_name or 'unknown'})",
                "Use a ReadWriteMany (Block) StorageClass so worker VMs can live migrate.",
                cluster=name,
            )
        for mapping in cluster["storage_class_mappings"]:
            mapped = _sc_supports_rwx(facts, mapping["infra"])
            rep.require(
                "storage.csi_mapping",
                "storage",
                _sc_by_name(facts, mapping["infra"]) is not None and mapped is not False,
                f"{name}: kubevirt-csi mapping {mapping['infra']} -> {mapping['guest']} "
                f"(infra class exists={_sc_by_name(facts, mapping['infra']) is not None}, RWX="
                f"{'yes' if mapped else 'no' if mapped is False else 'unknown'})",
                "KubeVirt CSI supports mapping only ReadWriteMany-capable infrastructure classes.",
                cluster=name,
            )
        # disconnected
        if cluster["disconnected"]["enabled"]:
            covered = [repo for repo in RELEASE_REPOS if repo in idms_sources]
            rep.require(
                "disconnected.mirrors",
                "disconnected",
                len(covered) == len(RELEASE_REPOS),
                f"{name}: management cluster ImageDigestMirrorSet/ImageContentSourcePolicy covers "
                f"{', '.join(covered) or 'no'} release repositories",
                "Apply the IDMS from oc-mirror so the HyperShift Operator can resolve the release payload.",
                cluster=name,
            )
            rep.recommend(
                "disconnected.digest",
                "disconnected",
                "@sha256:" in cluster["release_image"],
                f"{name}: release image "
                + ("pinned by digest" if "@sha256:" in cluster["release_image"] else "uses a tag, not a digest"),
                "Use the release image digest in disconnected environments (oc adm release info).",
                cluster=name,
            )
            rep.recommend(
                "disconnected.trust",
                "disconnected",
                bool(cluster["trust_bundle_configmap_name"]),
                f"{name}: additional trust bundle for the mirror registry CA "
                + ("set" if cluster["trust_bundle_configmap_name"] else "not set"),
                "Set additional_trust_bundle when the mirror registry uses a private CA.",
                cluster=name,
            )
            mirror_hosts = sorted(
                {
                    mirror.split("/")[0]
                    for entry in cluster["disconnected"]["image_content_sources"]
                    for mirror in entry["mirrors"]
                }
            )
            registries = set((pull.get(name) or {}).get("registries") or [])
            no_auth = [host for host in mirror_hosts if host not in registries]
            if mirror_hosts:
                rep.recommend(
                    "disconnected.mirror_auth",
                    "disconnected",
                    not no_auth,
                    f"{name}: pull secret has credentials for mirror registries"
                    + (f" (missing: {', '.join(no_auth)})" if no_auth else ""),
                    "Add the mirror registry credentials to the pull secret unless the mirror allows "
                    "anonymous pulls.",
                    cluster=name,
                )
            if version_compare(mgmt_version, "4.21") >= 0:
                rep.info(
                    "disconnected.capi_pin",
                    "disconnected",
                    f"{name}: management cluster {minor_version(mgmt_version)} needs "
                    "quay.io/openshift-release-dev/ocp-release:4.20.10-multi mirrored (documented known issue)",
                    cluster=name,
                )
    if any(c["disconnected"]["enabled"] for c in clusters):
        rep.recommend(
            "disconnected.management_ca",
            "disconnected",
            bool(facts.get("image_additional_trusted_ca")),
            "image.config.openshift.io additionalTrustedCA "
            + ("set" if facts.get("image_additional_trusted_ca") else "not set")
            + " on the management cluster",
            "Add the mirror registry CA to the management cluster (image.config.openshift.io/cluster).",
        )
    result = rep.result()
    # What deploy installs, with the channel and catalog source to use.
    plan = {}
    if mce_planned:
        plan["mce"] = {key: mce_plan[key] for key in ("channel", "version", "catalog_source", "catalog_source_namespace")}
    if virt_planned:
        plan["virtualization"] = {
            "channel": virt_pkg["default_channel"],
            "catalog_source": virt_pkg["catalog_source"],
            "catalog_source_namespace": virt_pkg["catalog_source_namespace"],
        }
    if any(c["id"] == "ingress.load_balancer" and c["status"] == "planned" for c in rep.checks):
        plan["metallb"] = {
            "channel": metallb_pkg.get("default_channel", ""),
            "catalog_source": metallb_pkg.get("catalog_source", ""),
            "catalog_source_namespace": metallb_pkg.get("catalog_source_namespace", ""),
            "operator_present": bool(metallb.get("instance_present")),
            "address_pools": metallb_pools,
        }
    result["install_plan"] = plan
    return result


def prereq_summary_lines(report):
    """Readable one-line-per-check summary, failures first."""
    order = {"fail": 0, "planned": 1, "warn": 2, "pass": 3, "info": 4}
    lines = []
    summary = (report or {}).get("summary") or {}
    lines.append(
        "READY: required prerequisites met" if (report or {}).get("ready")
        else f"NOT READY: {summary.get('required_failed', 0)} required prerequisite(s) missing"
    )
    lines.append(
        f"{summary.get('passed', 0)} passed, {summary.get('required_failed', 0)} missing, "
        f"{summary.get('planned', 0)} installed by deploy, "
        f"{summary.get('recommended_warnings', 0)} optional optimization(s)"
    )
    labels = {"fail": "MISSING", "planned": "WILL INSTALL", "warn": "OPTIONAL", "pass": "OK", "info": "INFO"}
    for check in sorted((report or {}).get("checks") or [], key=lambda c: order.get(c["status"], 9)):
        line = f"[{labels.get(check['status'], check['status'])}] {check['id']}: {check['message']}"
        if check["status"] in ("fail", "warn") and check.get("remediation"):
            line += f" -> {check['remediation']}"
        lines.append(line)
    return lines


# --------------------------------------------------------------------------
# lifecycle helpers
# --------------------------------------------------------------------------


def _get(data, path, default=None):
    current = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def immutable_drift(cluster, existing):
    """Compare immutable fields of a desired definition with an existing HostedCluster.

    Returns a list of ``{"field", "desired", "actual"}``. ADO reports drift and
    never patches immutable fields.
    """
    desired = hostedcluster_manifest(cluster)
    drift = []
    checks = (
        ("spec.platform.type", "platform type"),
        ("spec.platform.kubevirt.baseDomainPassthrough", "baseDomainPassthrough"),
        ("spec.platform.kubevirt.storageDriver", "kubevirt storageDriver"),
        ("spec.controllerAvailabilityPolicy", "controllerAvailabilityPolicy"),
        ("spec.olmCatalogPlacement", "olmCatalogPlacement"),
        ("spec.networking.clusterNetwork", "clusterNetwork"),
        ("spec.networking.serviceNetwork", "serviceNetwork"),
        ("spec.etcd.managed.storage.persistentVolume.storageClassName", "etcd storageClassName"),
        ("spec.capabilities", "capabilities"),
        ("spec.fips", "fips"),
        ("spec.dns.baseDomain", "dns.baseDomain"),
    )
    for path, label in checks:
        want = _get(desired, path)
        have = _get(existing or {}, path)
        if path == "spec.platform.kubevirt.baseDomainPassthrough":
            want, have = bool(want), bool(have)
        if path == "spec.capabilities":
            want = want or {}
            have = have or {}
        if path == "spec.olmCatalogPlacement":
            want = want or "management"
            have = have or "management"
        if path == "spec.etcd.managed.storage.persistentVolume.storageClassName" and not want:
            continue
        if path == "spec.dns.baseDomain" and cluster["base_domain_passthrough"]:
            continue
        if want != have:
            drift.append({"field": label, "desired": want, "actual": have})
    return drift


def hostedcluster_status(hc):
    """Summarize a HostedCluster resource (no secrets)."""
    hc = hc or {}
    status = hc.get("status") or {}
    conditions = status.get("conditions") or []
    history = (status.get("version") or {}).get("history") or []
    current = history[0] if history else {}
    # history[0] is the rollout in progress (state Partial) during an update.
    completed = next((h for h in history if _text(h.get("state")) == "Completed"), {})
    endpoint = status.get("controlPlaneEndpoint") or {}
    host = _text(endpoint.get("host"))
    port = endpoint.get("port") or 6443
    failing = [
        {"type": c.get("type"), "reason": c.get("reason"), "message": c.get("message")}
        for c in conditions
        if c.get("type") in (
            "ValidReleaseImage",
            "ValidConfiguration",
            "ValidHostedControlPlaneConfiguration",
            "SupportedHostedCluster",
            "ValidReleaseInfo",
            "ValidKubeVirtInfraNetworkMTU",
        )
        and _text(c.get("status")) == "False"
    ]
    return {
        "name": _get(hc, "metadata.name", ""),
        "namespace": _get(hc, "metadata.namespace", ""),
        "exists": bool(hc),
        "deleting": bool(_get(hc, "metadata.deletionTimestamp")),
        "platform": _get(hc, "spec.platform.type", ""),
        "available": _condition(conditions, "Available") == "True",
        "progressing": _condition(conditions, "Progressing") == "True",
        "degraded": _condition(conditions, "Degraded") == "True",
        "version": _text(current.get("version")),
        "version_state": _text(current.get("state")),
        "completed_version": _text(completed.get("version")),
        "desired_release_image": _get(hc, "spec.release.image", ""),
        "api_url": f"https://{host}:{port}" if host else "",
        "kubeconfig_secret": _get(status, "kubeconfig.name", "") or "",
        "kubeadmin_secret": _get(status, "kubeadminPassword.name", "") or "",
        "blocking_conditions": failing,
        "conditions": {c.get("type"): _text(c.get("status")) for c in conditions if c.get("type")},
    }


def nodepool_status(np):
    """Summarize a NodePool resource."""
    np = np or {}
    status = np.get("status") or {}
    conditions = status.get("conditions") or []
    spec = np.get("spec") or {}
    desired = spec.get("replicas")
    autoscaling = spec.get("autoScaling")
    current = status.get("replicas") or 0
    live = None
    for c in conditions:
        if c.get("type") == "KubeVirtNodesLiveMigratable":
            live = {"status": _text(c.get("status")), "message": _text(c.get("message"))}
    ready = _condition(conditions, "Ready") == "True"
    if autoscaling:
        converged = ready and current >= (autoscaling.get("min") or 0)
    else:
        converged = ready and desired is not None and current == desired
    return {
        "name": _get(np, "metadata.name", ""),
        "exists": bool(np),
        "desired_replicas": desired,
        "autoscaling": autoscaling,
        "current_replicas": current,
        "ready": ready,
        "all_machines_ready": _condition(conditions, "AllMachinesReady") == "True",
        "all_nodes_healthy": _condition(conditions, "AllNodesHealthy") == "True",
        "converged": converged,
        "version": _text(status.get("version")),
        "release_image": _get(np, "spec.release.image", ""),
        "live_migratable": live,
        "conditions": {c.get("type"): _text(c.get("status")) for c in conditions if c.get("type")},
    }


def upgrade_check(hc_version, target_version, supported_versions=None, nodepool_versions=None, mode="controlplane"):
    """Validate a hosted cluster or node pool version change.

    ``mode`` is ``controlplane`` (HostedCluster spec.release) or ``nodepool``.
    Rules from the 4.22 docs: no downgrades; the HyperShift Operator must list
    the target minor in supported-versions; node pools cannot be newer than
    the hosted cluster (patch included) and at most three minors older.
    """
    errors = []
    warnings = []
    target = parse_version(target_version)
    current = parse_version(hc_version)
    if not target:
        errors.append("target version is unknown; use a tagged release image or set the target version")
        return {"ok": False, "errors": errors, "warnings": warnings}
    supported = [minor_version(v) for v in supported_versions or [] if minor_version(v)]
    if mode == "controlplane":
        if current and version_compare(target, current) < 0:
            errors.append(f"downgrade from {current} to {target} is not supported")
        if current and version_compare(target, current) == 0:
            warnings.append(f"hosted cluster already at {current}")
        if supported and minor_version(target) not in supported:
            errors.append(
                f"{minor_version(target)} is not in the HyperShift supported-versions list "
                f"({', '.join(supported)}); update the multicluster engine Operator first"
            )
        distance = _minor_distance(target, current) if current else 0
        if distance is not None and distance > 1:
            warnings.append(
                f"{current} -> {target} spans {distance} minor versions; update one minor version at a time"
            )
        for pool_version in nodepool_versions or []:
            dist = _minor_distance(target, pool_version)
            if dist is not None and dist > 3:
                errors.append(
                    f"node pool version {pool_version} would be more than 3 minors behind {target}; "
                    "update node pools first"
                )
    else:
        if not current:
            errors.append(
                "the hosted control plane has not reported a completed version; "
                "update node pools after the control plane update completes"
            )
        if current and version_compare(target, current) > 0:
            errors.append(
                f"node pool version {target} cannot be newer than the hosted cluster {current} "
                "(update the control plane first and let it complete)"
            )
        dist = _minor_distance(current, target) if current else 0
        if dist is not None and dist > 3:
            errors.append(f"node pool version {target} is more than 3 minors behind the hosted cluster {current}")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def access_summary(hc, management_apps_domain=""):
    """Non-secret access details for a hosted cluster."""
    status = hostedcluster_status(hc)
    name = status["name"]
    namespace = status["namespace"]
    base = _get(hc or {}, "spec.dns.baseDomain", "") or ""
    passthrough = bool(_get(hc or {}, "spec.platform.kubevirt.baseDomainPassthrough", False))
    apps = ""
    if base:
        apps = f"apps.{name}.{base}"
    elif passthrough and management_apps_domain:
        apps = f"apps.{name}.{management_apps_domain}"
    kubeconfig = status["kubeconfig_secret"] or f"{name}-admin-kubeconfig"
    return {
        "name": name,
        "namespace": namespace,
        "hosted_control_plane_namespace": f"{namespace}-{name}",
        "api_url": status["api_url"],
        "console_url": f"https://console-openshift-console.{apps}" if apps else "",
        "apps_domain": apps,
        "kubeconfig_secret": {"namespace": namespace, "name": kubeconfig, "key": "kubeconfig"},
        "kubeadmin_password_secret": {
            "namespace": namespace,
            "name": status["kubeadmin_secret"] or f"{name}-kubeadmin-password",
            "key": "password",
        },
        "extract_kubeconfig_command": (
            f"oc extract -n {namespace} secret/{kubeconfig} --keys=kubeconfig --to=- > {name}.kubeconfig"
        ),
    }


def hosted_auth(kubeconfig):
    """kubernetes.core connection parameters that pin a hosted kubeconfig.

    ADO playbooks export K8S_AUTH_HOST/API_KEY/VERIFY_SSL (and AAP may add
    K8S_AUTH_SSL_CA_CERT) for the management cluster. kubernetes.core applies
    any of those that are set, even to an empty string, on top of a
    ``kubeconfig`` parameter, and a task cannot unset them. Explicit module
    parameters win, so hosted calls pass these values, all taken from the
    kubeconfig's current context. ``api_key`` is empty for client certificate
    kubeconfigs (the API server ignores an empty bearer token).
    ``ca_data`` must be written to a file for ``ca_cert``.

    The result can hold a bearer token: use it only under no_log.
    """
    kubeconfig = kubeconfig or {}

    def named(section, name):
        for entry in kubeconfig.get(section) or []:
            if entry.get("name") == name:
                return entry
        return {}

    context_name = _text(kubeconfig.get("current-context"))
    context = named("contexts", context_name).get("context") or {}
    cluster = named("clusters", context.get("cluster")).get("cluster") or {}
    user = named("users", context.get("user")).get("user") or {}
    return {
        "context": context_name,
        "host": _text(cluster.get("server")),
        "api_key": _text(user.get("token")),
        "validate_certs": not _as_bool(cluster.get("insecure-skip-tls-verify")),
        "ca_data": _text(cluster.get("certificate-authority-data")),
        "ca_file": _text(cluster.get("certificate-authority")),
    }


class FilterModule:
    """Shift on Shift (hosted control planes on OpenShift Virtualization) filters."""

    def filters(self):
        return {
            "hcp_kubevirt_normalize_cluster": normalize_cluster,
            "hcp_kubevirt_cluster_errors": cluster_errors,
            "hcp_kubevirt_cluster_definitions": cluster_definitions,
            "hcp_kubevirt_hostedcluster_manifest": hostedcluster_manifest,
            "hcp_kubevirt_nodepool_manifest": nodepool_manifest,
            "hcp_kubevirt_supporting_objects": supporting_objects,
            "hcp_kubevirt_pull_secret_check": pull_secret_check,
            "hcp_kubevirt_support_check": support_check,
            "hcp_kubevirt_prereq_report": prereq_report,
            "hcp_kubevirt_prereq_summary_lines": prereq_summary_lines,
            "hcp_kubevirt_immutable_drift": immutable_drift,
            "hcp_kubevirt_hostedcluster_status": hostedcluster_status,
            "hcp_kubevirt_nodepool_status": nodepool_status,
            "hcp_kubevirt_upgrade_check": upgrade_check,
            "hcp_kubevirt_access_summary": access_summary,
            "hcp_kubevirt_hosted_auth": hosted_auth,
            "hcp_kubevirt_package_facts": package_facts,
            "hcp_kubevirt_mce_channel": mce_channel,
            "hcp_kubevirt_package_options": package_options,
            "hcp_kubevirt_preferred_package": preferred_package,
            "hcp_kubevirt_node_facts": node_facts,
            "hcp_kubevirt_pod_requests": pod_requests,
            "hcp_kubevirt_condition_status": condition_status,
            "hcp_kubevirt_mce_facts": mce_facts,
            "hcp_kubevirt_mirror_sources": mirror_sources,
            "hcp_kubevirt_resource_refs": resource_refs,
            "hcp_kubevirt_access_reviews": access_reviews,
            "hcp_kubevirt_cluster_operator_facts": cluster_operator_facts,
            "hcp_kubevirt_storage_class_facts": storage_class_facts,
            "hcp_kubevirt_storage_profile_facts": storage_profile_facts,
            "hcp_kubevirt_snapshot_class_facts": snapshot_class_facts,
            "hcp_kubevirt_install_config_fips": install_config_fips,
            "hcp_kubevirt_parse_version": parse_version,
            "hcp_kubevirt_minor_version": minor_version,
            "hcp_kubevirt_version_compare": version_compare,
            "hcp_kubevirt_quantity_to_bytes": quantity_to_bytes,
            "hcp_kubevirt_cpu_to_millicores": cpu_to_millicores,
        }
