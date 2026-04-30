The taxonomy is organised into three top-level categories:

| Category | Description |
|---|---|
| `information` | The community carries metadata about a route (origin, type, location, validation status, etc.) without directly triggering a routing action |
| `action` | The community instructs a router to perform a specific routing operation (announce, suppress, prepend, blackhole, etc.), scoped to a direction and a target |
| `unknown` | The community's semantics could not be determined or do not fit any defined category |

The complete tree of valid tag values is shown below. Inline comments describe the meaning of each node.

```
semantic
│
├── information                        # Route carries informational metadata
│   ├── route_source                   # Identifies who originated or sent the route
│   │   └── source_scope
│   │       ├── asn                    # A specific AS number
│   │       ├── customer
│   │       ├── peer
│   │       ├── peer_group
│   │       ├── transit
│   │       ├── upstream
│   │       ├── downstream
│   │       ├── ixp
│   │       ├── internal
│   │       └── pop                    # Point of Presence
│   │
│   ├── route_type                     # Classifies the functional role of the route
│   │   └── (examples)
│   │       ├── self-originated
│   │       ├── locally originated
│   │       ├── customer route
│   │       ├── peer route
│   │       └── transit route
│   │
│   ├── location                       # Geographic tagging of the route
│   │   └── geo_scope
│   │       ├── international
│   │       ├── continent
│   │       ├── country
│   │       ├── region
│   │       ├── city
│   │       └── metro
│   │
│   ├── route_tag                      # Generic tag/mark with no stronger assignable semantics
│   │
│   ├── validation                     # Generic route validation / sanity / hygiene signal
│   │
│   ├── validation_rpki                # Route validity derived from RPKI
│   │
│   ├── validation_irr                 # Route validity derived from IRR
│   │
│   ├── performance                    # Network performance or cost metadata
│   │   └── metric
│   │       ├── rtt
│   │       ├── latency
│   │       ├── quality
│   │       └── cost
│   │
│   ├── security_state                 # Security-related route classification
│   │
│   └── mitigation_state               # DDoS or attack mitigation status
│
├── action                             # Community triggers a routing operation
│   └── action_model
│       │
│       ├── outbound                   # Operation applied when advertising routes to peers
│       │   ├── advertise              # Announce the route
│       │   │   ├── modifier
│       │   │   │   ├── prepend        # Add AS-PATH prepends
│       │   │   │   ├── med            # Set MED value
│       │   │   │   └── more_specific  # Advertise a more-specific prefix
│       │   │   └── scope
│       │   │       ├── peer_targeting # A specific peer or set of peers
│       │   │       ├── all_peers
│       │   │       ├── all_upstreams
│       │   │       ├── all_customers
│       │   │       └── l3vpn_evpn
│       │   │
│       │   ├── suppress               # Withdraw or stop advertising the route
│       │   │   └── scope
│       │   │       ├── peer_targeting
│       │   │       ├── all_peers
│       │   │       ├── all_upstreams
│       │   │       ├── all_customers
│       │   │       └── l3vpn_evpn
│       │   │
│       │   └── restrict               # Limit advertisement scope (e.g. no-export)
│       │       └── scope
│       │           ├── peer_targeting
│       │           ├── all_peers
│       │           ├── all_upstreams
│       │           ├── all_customers
│       │           └── l3vpn_evpn
│       │
│       ├── inbound                    # Operation applied when receiving routes from peers
│       │   ├── accept                 # Accept the route
│       │   │   ├── modifier
│       │   │   │   └── localpref      # Set Local Preference
│       │   │   └── scope
│       │   │       ├── peer_targeting
│       │   │       ├── all_peers
│       │   │       ├── all_upstreams
│       │   │       ├── all_customers
│       │   │       └── l3vpn_evpn
│       │   │
│       │   ├── reject                 # Reject / drop the route
│       │   │   └── scope
│       │   │       ├── peer_targeting
│       │   │       ├── all_peers
│       │   │       ├── all_upstreams
│       │   │       ├── all_customers
│       │   │       └── l3vpn_evpn
│       │   │
│       │   ├── validate               # Trigger route validation procedure
│       │   │   └── scope
│       │   │       ├── peer_targeting
│       │   │       ├── all_peers
│       │   │       ├── all_upstreams
│       │   │       ├── all_customers
│       │   │       └── l3vpn_evpn
│       │   │
│       │   ├── blackhole              # Trigger traffic blackholing (RTBH)
│       │   │   └── scope
│       │   │       ├── peer_targeting
│       │   │       ├── all_peers
│       │   │       ├── all_upstreams
│       │   │       ├── all_customers
│       │   │       └── l3vpn_evpn
│       │   │
│       │   ├── scrubbing              # Redirect traffic to a scrubbing centre
│       │   │   └── scope
│       │   │       ├── peer_targeting
│       │   │       ├── all_peers
│       │   │       ├── all_upstreams
│       │   │       ├── all_customers
│       │   │       └── l3vpn_evpn
│       │   │
│       │   ├── flowspec               # Trigger a FlowSpec rule
│       │   │   └── scope
│       │   │       ├── peer_targeting
│       │   │       ├── all_peers
│       │   │       ├── all_upstreams
│       │   │       ├── all_customers
│       │   │       └── l3vpn_evpn
│       │   │
│       │   └── next_hop_steering      # Override next-hop for traffic engineering
│       │       └── scope
│       │           ├── peer_targeting
│       │           ├── all_peers
│       │           ├── all_upstreams
│       │           ├── all_customers
│       │           └── l3vpn_evpn
│       │
│       └── both                       # Operation applies to both inbound and outbound
│           ├── accept
│           │   └── scope
│           │       ├── peer_targeting
│           │       ├── all_peers
│           │       ├── all_upstreams
│           │       ├── all_customers
│           │       └── l3vpn_evpn
│           │
│           ├── advertise
│           │   └── scope
│           │       ├── peer_targeting
│           │       ├── all_peers
│           │       ├── all_upstreams
│           │       ├── all_customers
│           │       └── l3vpn_evpn
│           │
│           └── restrict
│               └── scope
│                   ├── peer_targeting
│                   ├── all_peers
│                   ├── all_upstreams
│                   ├── all_customers
│                   └── l3vpn_evpn
│
└── unknown                            # Semantics could not be determined
    ├── unknown                        # Completely unclassifiable
    ├── inbound:unknown                # Direction known, operation unknown
    ├── outbound:unknown
    ├── both:unknown
    ├── inbound:action:unknown         # Direction and action class known, specifics unknown
    ├── outbound:action:unknown
    ├── both:action:unknown
    └── information:unknown            # Information community, specifics unknown
```
