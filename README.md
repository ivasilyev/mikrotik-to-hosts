# `mikrotik-to-hosts`
Get DHCP leases from MikroTik device and add them into the system `hosts` file

# Purpose
[MikroTik](https://mikrotik.com/) devices usually require a DHCP server lease script 
([example](https://blog.pessoft.com/2019/09/06/mikrotik-script-automatic-dns-records-from-dhcp-leases/)), 
which creates and deletes static DNS records automatically, 
based on creation and deletion of DHCP leases. 

This tool allows to treat the MikroTik device's DHCP leases as system hosts 
and may be useful for separate Linux DNS servers having advanced features onboard, 
e.g. [DNSCrypt proxy](https://github.com/DNSCrypt/dnscrypt-proxy) or
[Pi-hole](https://github.com/pi-hole/pi-hole).

# Setup

```shell script
# Install packages
sudo apt-get update -y

sudo apt-get install \
    --yes \
    ssh \
    sshpass

# Add a SSH identity only if you do not have one
ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa -C "$(hostname)_ssh_key" -q -N "" && \
ssh-add ~/.ssh/id_rsa

# Export environment variables
export MIKROTIK_HOST="192.168.88.1"
export MIKROTIK_PORT=22
export MIKROTIK_USER="admin"
export MIKROTIK_PASSWORD=""

# Exchange SSH keys
unset HISTFILE
sshpass -p \
    "${MIKROTIK_PASSWORD}" \
    ssh-copy-id \
        -i "${HOME}/.ssh/id_rsa.pub" \
        -o 'StrictHostKeyChecking=no' \
        -p ${MIKROTIK_PORT} \
    "${MIKROTIK_USER}@${MIKROTIK_HOST}"

# Empty the input
clear
```

# Probe MikroTik device connectivity manually

```shell script
ssh -t "${MIKROTIK_USER}@${MIKROTIK_HOST}" -p ${MIKROTIK_PORT} "
    /ip dhcp-server lease; 
    :foreach i in=[find] do={ 
        :put ([get \$i address].\",\".[get \$i host-name ])
    }; 
    :delay 1000ms;
    /quit;
"
```
