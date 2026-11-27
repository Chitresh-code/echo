#!/bin/sh
# Installs the jail firewall, DNS for the jails and the jail cgroups, then runs the given command (the runner). Any failure stops the
# container, so jails are never on the network without the firewall.
set -eu

if [ "${RUNNER_JAIL_NETWORK:-1}" = "1" ]; then
  # Each workspace's jails run in its own network namespace (app/net.py), joined to this container
  # by a veth named ew<n> in 10.89.0.0/16. Their traffic is forwarded and NATed here, so the rules
  # match on those interfaces. Docker gives this container a fresh netfilter state on every start,
  # but chains are still flushed rather than assumed empty.
  nameservers=$(awk '$1 == "nameserver" { print $2 }' /etc/resolv.conf)
  echo 1 > /proc/sys/net/ipv4/ip_forward

  chain() { "$1" -N "$2" 2>/dev/null || "$1" -F "$2"; }
  jump() { t=$1; shift; "$t" -C "$@" 2>/dev/null || "$t" -A "$@"; }

  # Out of a workspace: never to private, loopback, link-local (cloud metadata), shared or
  # reserved ranges. These cover the api container, this container, Docker's networks and every
  # other workspace (10.89.0.0/16 is inside 10.0.0.0/8).
  chain iptables ECHO_FWD
  for net in 127.0.0.0/8 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16 100.64.0.0/10 0.0.0.0/8 224.0.0.0/4 240.0.0.0/4; do
    iptables -A ECHO_FWD -d "$net" -j REJECT
  done
  iptables -A ECHO_FWD -j ACCEPT
  iptables -P FORWARD DROP
  jump iptables FORWARD -i ew+ -j ECHO_FWD
  # Into a workspace: only replies to its own connections.
  jump iptables FORWARD -o ew+ -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  iptables -t nat -C POSTROUTING -s 10.89.0.0/16 ! -o ew+ -j MASQUERADE 2>/dev/null \
    || iptables -t nat -A POSTROUTING -s 10.89.0.0/16 ! -o ew+ -j MASQUERADE

  # To this container itself a workspace may only ask dnsmasq for names.
  chain iptables ECHO_IN
  iptables -A ECHO_IN -p udp --dport 53 -j ACCEPT
  iptables -A ECHO_IN -p tcp --dport 53 -j ACCEPT
  iptables -A ECHO_IN -j DROP
  jump iptables INPUT -i ew+ -j ECHO_IN

  # Workspaces get no IPv6 address; drop anyway in case one ever has a route.
  ip6tables -P FORWARD DROP
  jump ip6tables INPUT -i ew+ -j DROP

  # DNS for the workspaces, answered on each ew<n> address (bind-dynamic picks up interfaces made
  # later) and forwarded to this container's resolvers, which a namespace cannot reach: on a
  # compose network that is Docker's resolver on 127.0.0.11.
  servers=""
  for ns in $nameservers; do servers="$servers --server=$ns"; done
  # shellcheck disable=SC2086
  dnsmasq --no-resolv $servers --user=nobody --bind-dynamic --interface='ew*' --except-interface=lo --no-hosts --cache-size=1000
fi

# Jail memory and process limits use cgroup v2. A cgroup can hand controllers to its children only
# while it holds no processes itself, so every process here moves into init/ first; nsjail then
# makes one child of jails/ per command. Fails the start if the controllers cannot be enabled.
cg=/sys/fs/cgroup
mkdir -p "$cg/init" "$cg/jails"
for pid in $(cat "$cg/cgroup.procs"); do
  # A process may exit between the read and the move.
  echo "$pid" > "$cg/init/cgroup.procs" 2>/dev/null || true
done
echo "+memory +pids" > "$cg/cgroup.subtree_control"
echo "+memory +pids" > "$cg/jails/cgroup.subtree_control"

exec "$@"
