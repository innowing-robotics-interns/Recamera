#!/usr/bin/env sh
# One-time fix for a reCamera firmware quirk: Node.js ships without Intl, so
# Node-RED's i18next translations crash with "Intl is not defined". This copies
# a tiny polyfill and loads it from the (user-writable) Node-RED settings file.
#
# Usage: ./tools/install_intl_polyfill.sh [camera-ip] [ssh-user]
# Default user is "recamera"; you will be asked for its password.
set -eu

IP="${1:-192.168.42.1}"
USER="${2:-recamera}"
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SETTINGS="/home/$USER/.node-red/settings.js"
POLYFILL="/home/$USER/intl-polyfill.js"

echo "[*] copying polyfill to $USER@$IP:$POLYFILL"
scp "$HERE/intl-polyfill.js" "$USER@$IP:$POLYFILL"

if ssh "$USER@$IP" "grep -q intl-polyfill '$SETTINGS'"; then
    echo "[*] settings.js already loads the polyfill"
    CHANGED=0
else
    echo "[*] patching $SETTINGS (backup: settings.js.bak-intl)"
    ssh "$USER@$IP" "cp '$SETTINGS' '$SETTINGS.bak-intl' && sed -i \"1i require('$POLYFILL');\" '$SETTINGS'"
    CHANGED=1
fi

if [ "$CHANGED" = 1 ]; then
    echo "[*] restarting Node-RED (this can take ~1 minute)"
    ssh "$USER@$IP" "sh /etc/init.d/S03node-red restart" || true
fi

echo "[*] waiting for Node-RED at http://$IP:1880"
i=0
while [ "$i" -lt 90 ]; do
    if curl -fsS "http://$IP:1880/flows/state" >/dev/null 2>&1; then
        echo "[+] Node-RED is up"
        exit 0
    fi
    i=$((i + 1))
    sleep 2
done
echo "[!] Node-RED did not come up; reboot the camera and run 'recamera wait'" >&2
exit 1
