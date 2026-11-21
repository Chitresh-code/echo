#!/bin/sh
# Installs the jail firewall, then runs the given command (the runner). Any failure stops the
# container, so jails are never on the network without the firewall.
set -eu

if [ "${RUNNER_JAIL_NETWORK:-1}" = "1" ]; then
  uid="${RUNNER_JAIL_UID:-1000}"
  nameservers=$(awk '$1 == "nameserver" { print $2 }' /etc/resolv.conf)

  for tool in iptables ip6tables; do
    # A chain of our own, rebuilt on every start, with one jump to it for the jail user.
    "$tool" -N ECHO_JAIL 2>/dev/null || "$tool" -F ECHO_JAIL
    "$tool" -C OUTPUT -m owner --uid-owner "$uid" -j ECHO_JAIL 2>/dev/null \
      || "$tool" -A OUTPUT -m owner --uid-owner "$uid" -j ECHO_JAIL
  done

  # DNS to the configured resolvers first, since they are often on private or loopback
  # addresses. Matched on the original destination: Docker's embedded resolver at 127.0.0.11
  # is reached through a NAT rule that rewrites the port before this filter sees the packet.
  for ns in $nameservers; do
    case "$ns" in *:*) tool=ip6tables ;; *) tool=iptables ;; esac
    for proto in udp tcp; do
      "$tool" -A ECHO_JAIL -p "$proto" -m conntrack --ctorigdst "$ns" --ctorigdstport 53 -j ACCEPT
    done
  done

  for net in 127.0.0.0/8 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16 100.64.0.0/10 0.0.0.0/8 224.0.0.0/4 240.0.0.0/4; do
    iptables -A ECHO_JAIL -d "$net" -j REJECT
  done
  for net in ::1/128 fc00::/7 fe80::/10 ff00::/8 ::ffff:0:0/96; do
    ip6tables -A ECHO_JAIL -d "$net" -j REJECT
  done
fi

exec "$@"
