#!/bin/bash
# Starts VNC + noVNC (if LAB_DESKTOP=1) then runs the command; stops everything on TERM/INT.
# Xtigervnc ALWAYS listens on the container loopback only (5901 never leaves the container).
# websockify listens on 0.0.0.0:6080 INSIDE the container; the host must publish it on 127.0.0.1 only
# (docker run -p 127.0.0.1:6080:6080).
set -u
umask 077
pids=()
cleanup() {
  for p in "${pids[@]}"; do kill "$p" 2>/dev/null; done
  wait 2>/dev/null
  exit 0
}
trap cleanup TERM INT

if [ "${LAB_DESKTOP:-1}" = "1" ]; then
  mkdir -p "$HOME/.vnc"
  chmod 700 "$HOME/.vnc"
  pw="${LAB_VNC_PASSWORD:-}"
  if [ -z "$pw" ]; then
    pw="$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 16)"
    echo "lab: LAB_VNC_PASSWORD not set, generated one"
  fi
  printf '%s' "$pw" > "$HOME/.vnc/passwd-plain"
  chmod 600 "$HOME/.vnc/passwd-plain"
  printf '%s' "$pw" | vncpasswd -f > "$HOME/.vnc/passwd"
  chmod 600 "$HOME/.vnc/passwd"
  unset pw LAB_VNC_PASSWORD
  echo "lab: VNC password is in $HOME/.vnc/passwd-plain (mode 600)"

  Xtigervnc :1 -rfbport 5901 -rfbauth "$HOME/.vnc/passwd" -SecurityTypes VncAuth \
    -geometry "${LAB_GEOMETRY:-1440x900}" -depth 24 -localhost yes >"$HOME/.vnc/xvnc.log" 2>&1 &
  pids+=($!)
  for _ in $(seq 1 50); do [ -S /tmp/.X11-unix/X1 ] && break; sleep 0.2; done
  DISPLAY=:1 dbus-launch --exit-with-session startxfce4 >"$HOME/.vnc/xfce.log" 2>&1 &
  pids+=($!)
  websockify --web /usr/share/novnc 0.0.0.0:6080 127.0.0.1:5901 >"$HOME/.vnc/novnc.log" 2>&1 &
  pids+=($!)
  echo "lab: desktop up inside the container on :6080 (open /vnc.html); publish it on 127.0.0.1 only"
fi

"$@" &
pids+=($!)
wait $!
rc=$?
cleanup
exit $rc
