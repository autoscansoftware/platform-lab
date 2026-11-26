#!/bin/bash
# Starts VNC + noVNC (if LAB_DESKTOP=1) then runs the command; stops everything on TERM/INT.
set -u
pids=()
cleanup() {
  for p in "${pids[@]}"; do kill "$p" 2>/dev/null; done
  wait 2>/dev/null
  exit 0
}
trap cleanup TERM INT

if [ "${LAB_DESKTOP:-1}" = "1" ]; then
  pw="${LAB_VNC_PASSWORD:-}"
  if [ -z "$pw" ]; then
    pw="$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 8)"
    echo "lab: LAB_VNC_PASSWORD not set, generated one starting with ${pw:0:4}..."
  fi
  bind="${LAB_BIND:-127.0.0.1}"
  mkdir -p "$HOME/.vnc"
  printf '%s' "$pw" | vncpasswd -f > "$HOME/.vnc/passwd"
  chmod 600 "$HOME/.vnc/passwd"
  unset pw LAB_VNC_PASSWORD

  lh=(); [ "$bind" = "127.0.0.1" ] && lh=(-localhost yes)
  Xtigervnc :1 -rfbport 5901 -rfbauth "$HOME/.vnc/passwd" -SecurityTypes VncAuth \
    -geometry "${LAB_GEOMETRY:-1440x900}" -depth 24 "${lh[@]}" >"$HOME/.vnc/xvnc.log" 2>&1 &
  pids+=($!)
  for _ in $(seq 1 50); do [ -S /tmp/.X11-unix/X1 ] && break; sleep 0.2; done
  DISPLAY=:1 dbus-launch --exit-with-session startxfce4 >"$HOME/.vnc/xfce.log" 2>&1 &
  pids+=($!)
  websockify --web /usr/share/novnc "$bind:6080" 127.0.0.1:5901 >"$HOME/.vnc/novnc.log" 2>&1 &
  pids+=($!)
  echo "lab: desktop up on $bind:6080 (open /vnc.html)"
fi

"$@" &
pids+=($!)
wait $!
rc=$?
cleanup
exit $rc
