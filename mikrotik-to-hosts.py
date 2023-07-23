#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
from subprocess import getoutput as go


def query_mikrotik_command(cmd, user, host, port):
    o = go("""
        ssh -t %s@%s -p %s \"
            %s;
            :delay 1000ms;
            /quit;
        \"
    """ % (user, host, port, cmd))
    o_1 = str(o)
    for char in ("\r", "\x1b", "[9999B"):
        o_1 = o_1.replace(char, "")
    o_1 = o_1.split("\ninterrupted\n")[0].strip()
    return o_1


def poll_mikrotik_host_name(user, host, port):
    return query_mikrotik_command(":put [/system identity get name]", user, host, port)


def poll_mikrotik_board_name(user, host, port):
    return query_mikrotik_command(":put [/system resource get board-name]", user, host, port)


def poll_mikrotik_hosts(user, host, port):
    s = query_mikrotik_command("""
        /ip dhcp-server lease;
        :foreach i in=[find] do={
            :put ([get \$i address].\\\"\\t\\\".[get \$i host-name ])
        };
    """, user, host, port)
    lines = [
        j for j in [
            i.strip().split("\t") for i in sorted(re.split("\n", s))
            if len(i) > 0
        ] if len(j) == 2
    ]
    return lines


def get_mikrotik_hosts(user, host, port):
    out = [dict(ip=host, hostname=poll_mikrotik_board_name(user, host, port))]
    for line in poll_mikrotik_hosts(user, host, port):
        out.append(dict(ip=line[0], hostname=line[1]))
    return out

