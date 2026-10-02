# Role: infra.ado.ocp_metallb_install

Install the MetalLB Operator, create the MetalLB instance, and configure
IPAddressPools, L2Advertisements, BGPPeers, and BGPAdvertisements for
bare-metal LoadBalancer service support.

## Role Author

Automation Development Office

## ✅ Role Requirements

- OpenShift cluster (bare-metal or platform without cloud load balancer)
- `kubernetes.core` collection
- `infra.ado` collection (ocp_operator_subscription, ocp_wait_operator)

## 📦 Role Variables

| Variable | Default | Description |
|---|---|---|
| `ocp_metallb_namespace` | `metallb-system` | Operator namespace |
| `ocp_metallb_operator_name` | `metallb-operator` | Operator package |
| `ocp_metallb_operator_channel` | `stable` | OLM channel |
| `ocp_metallb_instance_name` | `metallb` | MetalLB CR name |
| `ocp_metallb_config.enabled` | `false` | Enable MetalLB |
| `ocp_metallb_config.address_pools` | `[]` | IPAddressPool definitions |
| `ocp_metallb_config.l2_advertisements` | `[]` | L2Advertisement definitions |
| `ocp_metallb_config.bgp_peers` | `[]` | BGPPeer definitions |
| `ocp_metallb_config.bgp_advertisements` | `[]` | BGPAdvertisement definitions |

## 🚀 Role Usage

```yaml
- hosts: localhost
  roles:
    - role: infra.ado.ocp_metallb_install
      vars:
        ocp_metallb_config:
          enabled: true
          address_pools:
            - name: external-pool
              addresses:
                - 192.168.100.200-192.168.100.250
          l2_advertisements:
            - name: external-l2
              ip_address_pools:
                - external-pool
```

## 🧪 Role Molecule Testing

```bash
cd extensions/molecule && ln -sfn . molecule
molecule test -s ocp_metallb_install
```

## 📁 Role Structure

```
roles/ocp_metallb_install/
├── defaults/
│   └── main.yml
├── meta/
│   └── main.yml
├── tasks/
│   └── main.yml
└── README.md
```
