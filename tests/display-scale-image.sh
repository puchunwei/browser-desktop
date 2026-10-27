#!/usr/bin/env bash
# End-to-end density regression. Fresh disposable data, loopback listeners only.
set -euo pipefail
umask 077
HERE=$(cd -- "$(dirname -- "$0")" && pwd)
REPO=$(dirname "$HERE")
image=${1:?image reference}
evidence=${2:?private evidence directory}
read -r -a docker <<< "${DOCKER:-docker}"
name="bd-density-$$"
client="$name-client"
rdp_port=${RDP_TEST_PORT:-13392}
cdp_port=${CDP_TEST_PORT:-19392}
mkdir -p "$evidence"
evidence=$(cd "$evidence" && pwd)
# Avoid stale request/response handshakes from previous runs; retain all evidence.
[[ ! -e "$evidence/container-id" ]] || { echo 'Use a fresh evidence directory' >&2; exit 2; }
cleanup() {
    result=$?
    trap - EXIT
    "${docker[@]}" logs "$client" > "$evidence/client.log" 2>&1 || true
    "${docker[@]}" logs "$name" > "$evidence/server.log" 2>&1 || true
    "${docker[@]}" rm -f "$client" >/dev/null 2>&1 || true
    if [[ $("${docker[@]}" inspect -f '{{.State.Running}}' "$name" 2>/dev/null) == true ]]; then
        mkdir -p "$evidence/xorg-logs"
        # docker cp cannot read this runtime tmpfs on every Docker backend.
        if ! "${docker[@]}" exec "$name" tar -C /run/xrdp/test-logs -cf - . |
                tar --no-same-owner -xf - -C "$evidence/xorg-logs"; then
            echo 'FAIL: could not preserve disposable Xorg logs' >&2
            result=1
        fi
    fi
    "${docker[@]}" stop -t 30 "$name" >/dev/null 2>&1 || true
    "${docker[@]}" rm -f "$name" >/dev/null 2>&1 || true
    rm -f "$evidence/password"
    exit "$result"
}
trap cleanup EXIT
"${docker[@]}" run -d --name "$name" --label browser-desktop.test=display-scale \
    --shm-size 2g --tmpfs /run/xrdp:rw,nosuid,nodev,size=16m,mode=0755 \
    --security-opt "seccomp=$REPO/seccomp/chrome.json" \
    -p "127.0.0.1:$rdp_port:3389" -p "127.0.0.1:$cdp_port:9222" \
    -v "$evidence:/evidence" -v "$HERE/display-scale-source.py:/test-source.py:ro" \
    -v "$HERE/xorg-test-entrypoint.sh:/test-entrypoint.sh:ro" \
    --entrypoint /bin/bash -e CDP_BIND_ADDRESS=0.0.0.0 "$image" /test-entrypoint.sh > "$evidence/container-id"
for _ in $(seq 1 60); do
    status=$("${docker[@]}" inspect -f '{{.State.Health.Status}}' "$name")
    [[ $status == healthy ]] && break
    sleep 2
done
[[ $status == healthy ]] || { echo 'Synthetic desktop did not become healthy' >&2; exit 1; }
"${docker[@]}" cp "$name:/data/rdp/password" "$evidence/password"
client_image=${RDP_CLIENT_IMAGE:-browser-desktop-rdp-client:density}
if [[ -z ${RDP_CLIENT_IMAGE:-} ]]; then
    base_args=()
    [[ -z ${DEBIAN_IMAGE:-} ]] || base_args+=(--build-arg "DEBIAN_IMAGE=$DEBIAN_IMAGE")
    "${docker[@]}" build --network host --build-arg "APT_MIRROR=${APT_MIRROR:-http://deb.debian.org}" \
        "${base_args[@]}" --build-arg "HTTP_PROXY=${HTTP_PROXY:-}" --build-arg "HTTPS_PROXY=${HTTPS_PROXY:-}" \
        --build-arg "NO_PROXY=${NO_PROXY:-}" -t "$client_image" "$HERE/rdp-client" \
        > "$evidence/client-build.log" 2>&1
fi
"${docker[@]}" run -d --init --name "$client" --label browser-desktop.test=display-scale-client --network host \
    -v "$evidence/password:/pw:ro" -v "$evidence:/evidence" \
    -v "$HERE/rdp-client/display-scale.py:/display-scale.py:ro" \
    -e "DENSITY_BASELINE=${DENSITY_BASELINE:-0}" -e "DENSITY_FIXED_ONLY=${DENSITY_FIXED_ONLY:-0}" \
    "$client_image" timeout 600 xvfb-run -a -s '-screen 0 6200x3500x24' \
    python3 -u /display-scale.py 127.0.0.1 "$rdp_port" "$cdp_port" > "$evidence/client-id"
# The client asks only for bounded test actions against this task's server.
# No arbitrary shell, profile reads, or access to other containers is exposed.
while [[ $("${docker[@]}" inspect -f '{{.State.Running}}' "$client") == true ]]; do
    if [[ -f "$evidence/request" ]]; then
        read -r number action phase < "$evidence/request"
        rm "$evidence/request"
        [[ $number =~ ^[0-9]+$ && ${phase:-safe} =~ ^[a-z0-9-]+$ ]] || exit 2
        case "$action" in
            snapshot)
                "${docker[@]}" exec "$name" python3 /test-source.py "/evidence/$phase-source.ppm"
                "${docker[@]}" logs "$name" > "$evidence/$phase-server.log" 2>&1
                "${docker[@]}" stats --no-stream --format '{{json .}}' "$name" > "$evidence/$phase-cost.json"
                "${docker[@]}" exec "$name" python3 -c '
import json,os,pathlib,re,subprocess
status=json.loads(subprocess.check_output(["/usr/local/bin/display-scale.py","status"]))
pids={name:subprocess.check_output(["pgrep","-o","-x",name],text=True).strip() for name in ["chrome","Xorg","xrdp-sesexec","openbox"]}
rss_kib={name:int(pathlib.Path("/proc/"+pid+"/status").read_text().split("VmRSS:")[1].split()[0]) for name,pid in pids.items()}
memory_file=pathlib.Path("/sys/fs/cgroup/memory.stat")
memory_stat=dict(line.split() for line in memory_file.read_text().splitlines()) if memory_file.exists() else {}
bitmap_compression=next(line.split("=",1)[1] for line in pathlib.Path("/etc/xrdp/xrdp.ini").read_text().splitlines() if line.startswith("bitmap_compression="))
network={key:int(pathlib.Path("/sys/class/net/eth0/statistics/"+key+"_bytes").read_text()) for key in ["rx","tx"]}
os.environ.update(dict(line.split("=",1) for line in pathlib.Path("/run/browser-desktop/session").read_text().splitlines()))
clients=subprocess.check_output(["xprop","-root","_NET_CLIENT_LIST"],text=True)
windows=re.findall(r"0x[0-9a-f]+",clients)
assert len(windows)==1
geometry=subprocess.check_output(["xwininfo","-id",windows[0]],text=True)
window_pixels=[int(re.search(r"\n\s*"+key+r": (\d+)",geometry).group(1)) for key in ["Width","Height"]]
properties=subprocess.check_output(["xprop","-id",windows[0],"WM_NORMAL_HINTS","_NET_WM_STATE","WM_CLASS"],text=True)
menu_config=pathlib.Path("/home/browser/.config/openbox/rc.xml").read_text()
print(json.dumps(dict(window_properties=properties,menu_config=menu_config,status=status,pids=pids,rss_kib=rss_kib,resident_anon_bytes=int(memory_stat["anon"]) if "anon" in memory_stat else None,bitmap_compression=bitmap_compression,network_bytes=network,window_pixels=window_pixels)))' > "$evidence/response-$number.tmp"
                ;;
            bitmap-live)
                # Fixture-only control: FreeRDP 3.15 security backport retains
                # the initial planar decoder bounds across a live resize.
                "${docker[@]}" exec "$name" sed -i 's/^bitmap_compression=.*/bitmap_compression=false/' /etc/xrdp/xrdp.ini
                echo '{}' > "$evidence/response-$number.tmp"
                ;;
            recover)
                # The shipping supervisor deliberately exposes no control socket.
                # Inject failure only into the unique controller in this fixture.
                "${docker[@]}" exec "$name" python3 -c '
import os,pathlib,signal
matches=[]
for process in pathlib.Path("/proc").glob("[0-9]*"):
    try:
        argv=(process/"cmdline").read_bytes().split(b"\0")[:-1]
    except (FileNotFoundError,ProcessLookupError):
        continue
    if len(argv)==3 and pathlib.Path(os.fsdecode(argv[0])).name=="python3" and argv[1:]==[b"/usr/local/bin/display-scale.py",b"serve"]:
        matches.append(int(process.name))
assert len(matches)==1, "expected one disposable density controller"
os.kill(matches[0],signal.SIGKILL)'
                sleep 2
                echo '{}' > "$evidence/response-$number.tmp"
                ;;
            *) exit 2 ;;
        esac
        mv "$evidence/response-$number.tmp" "$evidence/response-$number.json"
    fi
    sleep .2
done
code=$("${docker[@]}" inspect -f '{{.State.ExitCode}}' "$client")
"${docker[@]}" logs "$client" > "$evidence/client.log" 2>&1
cat "$evidence/client.log"
[[ $code == 0 ]] || exit "$code"
python3 - "$evidence/result.json" <<'PY'
import json,sys
results=json.load(open(sys.argv[1]))
assert len({json.dumps(r['host']['pids'],sort_keys=True) for r in results}) == 1, 'Desktop/browser process identity changed'
print('PASS: one Chrome/Xorg/session process across all density transitions')
PY
if [[ ${DENSITY_VERIFY_LEGACY:-0} == 1 ]]; then
    # Legacy color-derived pointer targets assume settled 100% Chrome geometry.
    # Keep their original gates independent of the matrix's final 300% session.
    RDP_TEST_PORT=$((rdp_port+1)) CDP_TEST_PORT=$((cdp_port+1)) \
        bash "$HERE/verify-image.sh" "$image" "$evidence/legacy"
fi
