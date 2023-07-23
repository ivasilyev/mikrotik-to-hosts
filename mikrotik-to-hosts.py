#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import logging
from shutil import copy2
from subprocess import getoutput
from argparse import ArgumentParser


HOSTS_FILE = "/etc/hosts"
DEFAULT_SUFFIX = "lan"


def join_lines(s: str):
    return re.sub("[\r\n ]+", " ", s)


def go(cmd: str):
    o = getoutput(cmd)
    logging.debug(f"Ran command: '{join_lines(cmd)}' with the output: '{o}'")
    return o


def split_lines(s: str):
    return [i.strip() for i in re.split("[\r\n]+", s)]


def split_columns(s: str, is_space_delimiter: bool = False):
    r = "[\t]+"
    if is_space_delimiter:
        r = "[\t ]+"
    return [i.strip() for i in re.split(r, s)]


def check_suffix(s: str):
    s = s.strip(" ,.")
    if len(s) == 0 or s in ("local",):
        logging.info(f"Invalid suffix: '{s}', use default instead: '{DEFAULT_SUFFIX}'")
        return DEFAULT_SUFFIX
    return s


def remove_empty_values(x: list):
    return [i for i in x if len(i) > 0]


def is_ip_loopback(s: str):
    return any(s.startswith(i) for i in ["127.", "::1", "fe00:", "ff00:", "ff02:"])


def is_ip_valid(s: str):
    return (
        len(s) > 0
        and not is_ip_loopback(s)
        and len(re.findall("[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}", s)) > 0
    )


def is_hosts_line_valid(s: str):
    return (
        len(s) == 0
        or is_ip_loopback(s)
        or is_ip_valid(s)
        or s.startswith("#")
        or s.startswith(";")
    )


def is_hostname_valid(s: str):
    return (
        s is not None
        and len(s) > 0
        and len(re.findall("[^A-Za-z0-9\.\-_]+", s)) == 0
        # .local conflicts with Multicast DNS
        and not s.endswith(".local")
        and s not in ("*", "?", "_gateway")
    )


def validate_hostname(s: str):
    if is_hostname_valid(s):
        s = s.lower().strip()
        return re.sub("[ _-]+", "-", s)
    return ""


def load_string(file: str):
    logging.debug(f"Read file: '{file}'")
    with open(file, mode="r", encoding="utf-8") as f:
        o = f.read()
        f.close()
    return o


def dump_string(s: str, file: str):
    logging.debug(f"Write file: '{file}'")
    with open(file, mode="w", encoding="utf-8") as f:
        f.write(s)
        f.close()


def load_hosts(file: str):
    o = split_lines(load_string(file))
    out = [i for i in o if is_hosts_line_valid(i)]
    logging.debug(f"Read {len(out)} lines")
    return out


def join_table(list_of_lists: list):
    return "\n".join(["\t".join([str(column) for column in row]) for row in list_of_lists]) + "\n"


def flush_dns():
    logging.info("Flush DNS caches")
    o = go("resolvectl flush-caches").strip()
    if len(o) > 0:
        logging.warning(f"DNS cache flush attempt finished unexpectedly: '{o}'")
    logging.info("Restart DNS")
    o = go("systemctl restart systemd-hostnamed").strip()
    if len(o) > 0:
        logging.warning(f"DNS restart attempt finished unexpectedly: '{o}'")


def get_logging_level():
    var = os.getenv("LOGGING_LEVEL", None)
    if (
        var is not None
        and len(var) > 0
        and hasattr(logging, var)
    ):
        val = getattr(logging, var)
        if isinstance(val, int) and val in [i * 10 for i in range(0, 6)]:
            return val
    return logging.ERROR


def validate_new_hostnames(dicts: list):
    out = list()
    for d in dicts:
        if (
            "hostname" in d.keys()
            and is_ip_valid(d.get("ip"))
        ):
            hostname = validate_hostname(d.get("hostname"))
            if is_hostname_valid(hostname):
                out.append(dict(ip=d.get("ip"), hostname=hostname))
    return sorted(out, key=lambda x: x.get("ip"))


def process_hosts_table(table: list, hostnames: dict, suffix: str):
    suffix = f".{suffix}"
    hostnames_with_suffixes = dict()
    for ip, hostname in hostnames.items():
        if not hostname.endswith(suffix):
            hostname = f"{hostname}{suffix}"
        hostnames_with_suffixes[ip] = hostname
    new_hostnames = list(hostnames.values()) + list(hostnames_with_suffixes.values())
    out_lines = list()
    for line in table:
        columns = remove_empty_values(split_columns(line, is_space_delimiter=True))
        if len(columns) == 0:
            out_lines.append([line])
            continue
        ip = columns[0]
        if not is_ip_valid(ip):
            out_lines.append([line])
            continue
        hostnames = [i for i in columns[1:] if i not in new_hostnames]
        if ip in hostnames_with_suffixes.keys():
            hostnames = [hostnames_with_suffixes.pop(ip)]
        out_lines.append([ip, *hostnames])
    logging.debug(f"New host names to add: '{hostnames_with_suffixes}'")
    extend_hostnames = list(hostnames_with_suffixes.items())
    out_lines.extend(extend_hostnames)
    return out_lines


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


def parse_args():
    p = ArgumentParser(description="This tool scans the network for the hosts telling their hostnames "
                                   "and updates the system hosts file",
                       epilog="")
    p.add_argument("-f", "--flush", help="(Optional) Flush DNS records", action="store_true")
    p.add_argument("-u", "--user", help="(Optional) MikroTik device user name", default="admin")
    p.add_argument("-t", "--host", help="(Optional) MikroTik device IP address", default="192.168.88.1")
    p.add_argument("-p", "--port", help="(Optional) MikroTik device SSH listen port", type=int, default=22)
    p.add_argument("-s", "--suffix", help="(Optional) Default suffix", default=DEFAULT_SUFFIX)
    ns = p.parse_args()
    return (
        ns.flush,
        ns.user,
        ns.host,
        ns.port,
        ns.suffix,
    )


if __name__ == '__main__':
    (
        input_is_flush,
        input_user,
        input_host,
        input_port,
        input_suffix,
    ) = parse_args()

    logger = logging.getLogger()
    logger.setLevel(get_logging_level())
    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter(
        u"%(filename)s[LINE:%(lineno)d]# %(levelname)-8s [%(asctime)s]  %(message)s")
    )
    logger.addHandler(stream)

    if input_is_flush:
        flush_dns()

    main_suffix = check_suffix(input_suffix)

    raw_hostname_dicts = get_mikrotik_hosts(user=input_user, host=input_host, port=input_port)

    hostname_dicts = validate_new_hostnames(raw_hostname_dicts)
    hostname_dict = {i["ip"]: i["hostname"] for i in hostname_dicts}
    logging.debug(f"Parsed hostnames are '{hostname_dict}'")

    new_hosts_lines = process_hosts_table(
        table=load_hosts(HOSTS_FILE),
        suffix=main_suffix,
        hostnames=hostname_dict,
    )

    backup_file = f"{HOSTS_FILE}.bak"
    if not os.path.exists(backup_file):
        copy2(HOSTS_FILE, backup_file)
        logging.info(f"Created backup: '{backup_file}'")

    new_hosts_content = join_table(new_hosts_lines)
    dump_string(new_hosts_content, HOSTS_FILE)
    logging.info("Hosts update completed")
