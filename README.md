# platform-lab

Generic, open-source tooling for running builds and tests on Windows, Linux, macOS, iOS and Android in parallel
(GitHub Actions runners) and for disposable GPU/VM lab pods on Vast.ai.

This repository is PUBLIC so that GitHub Actions minutes are free. Rules for everything committed here:
- No secrets, tokens, keys, passwords, hostnames, IP addresses or personal paths. Secrets are injected at run time
  by the operator's own machine, never stored in images or in this repo.
- No product source code. Product repos (private) call the reusable workflows here.
- Open-source dependencies only; images contain only public tools.

## Layout
- `docker/lab/`: the lab image (Ubuntu + browser-reachable desktop + common toolchains), built by CI and pushed to ghcr.io.
- `.github/workflows/`: the image build, a reusable OS matrix, Android emulator and iOS simulator smoke tests.
- `labctl/`: a small CLI to run several containers on one rented VM pod (run, push, pull, status, self-destruct).
- `examples/hello/`: a tiny cross-platform app used by the smoke tests.

Licence: MIT.
