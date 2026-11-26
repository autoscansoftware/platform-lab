# Lab image

Ubuntu 24.04 with an XFCE desktop reachable in a browser (noVNC on port 6080) and common toolchains:
git, build-essential, python3 (venv, pip, pipx), Node 22 (pinned), Docker CLI (client only), rsync, ssh, tmux, jq,
unzip, Google Chrome (also available as `chromium`; use `--no-sandbox` inside containers if needed).
Runs as non-root user `lab` (uid 1000, passwordless sudo inside the container only).

Image: `ghcr.io/autoscansoftware/lab:latest` (also `:sha-<short>`), built by `.github/workflows/lab-image.yml`.

## Run
    docker run --rm -e LAB_VNC_PASSWORD=choose-one -p 127.0.0.1:6080:6080 ghcr.io/autoscansoftware/lab:latest

Then open http://127.0.0.1:6080/vnc.html.

| env | default | meaning |
|---|---|---|
| `LAB_DESKTOP` | `1` | `0` skips the desktop and just runs the command |
| `LAB_VNC_PASSWORD` | random | VNC password (first 8 chars count). If unset, a random one is generated and only its first 4 characters are logged |
| `LAB_GEOMETRY` | `1440x900` | screen size |

Security: Xtigervnc always listens on the container loopback only (5901 never leaves the container). noVNC (websockify) listens on 0.0.0.0:6080 inside the container; publish it on the host loopback only (`-p 127.0.0.1:6080:6080`) and reach it over an ssh tunnel. The VNC password comes from `LAB_VNC_PASSWORD` or is generated, and is written to `/home/lab/.vnc/passwd-plain` (mode 0600, owner lab); it is never printed.