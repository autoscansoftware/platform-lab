FROM ubuntu:24.04

ARG NODE_VERSION=22.12.0
ARG DOCKER_CLI_VERSION=27.3.1
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl wget gnupg git build-essential \
      python3 python3-venv python3-pip pipx \
      rsync openssh-client tmux jq unzip xz-utils sudo less procps \
      xfce4 xfce4-terminal dbus-x11 x11-xserver-utils fonts-dejavu-core fonts-liberation \
      tigervnc-standalone-server tigervnc-common novnc websockify \
    && rm -rf /var/lib/apt/lists/*

# Node (official tarball, pinned, checksum verified)
RUN set -eux; \
    f="node-v${NODE_VERSION}-linux-x64.tar.xz"; \
    curl -fsSLO "https://nodejs.org/dist/v${NODE_VERSION}/${f}"; \
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/SHASUMS256.txt" | grep " ${f}\$" | sha256sum -c -; \
    tar -xJf "$f" -C /usr/local --strip-components=1; \
    rm "$f"; node --version

# Docker CLI (client only)
RUN set -eux; \
    curl -fsSL "https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_CLI_VERSION}.tgz" \
      | tar -xz -C /usr/local/bin --strip-components=1 docker/docker; \
    docker --version

# Chrome (Ubuntu's chromium is snap-only); `chromium` is an alias for headless jobs
RUN set -eux; \
    curl -fsSL -o /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb; \
    apt-get update; apt-get install -y --no-install-recommends /tmp/chrome.deb; \
    rm -rf /tmp/chrome.deb /var/lib/apt/lists/*; \
    ln -s /usr/bin/google-chrome-stable /usr/local/bin/chromium

# Non-root user (uid 1000); sudo works only inside the container
RUN userdel -r ubuntu 2>/dev/null || true; \
    useradd -m -u 1000 -s /bin/bash lab; \
    echo "lab ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/lab; chmod 0440 /etc/sudoers.d/lab

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER lab
WORKDIR /home/lab
ENV LAB_DESKTOP=1 DISPLAY=:1
EXPOSE 6080
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["sleep", "infinity"]
