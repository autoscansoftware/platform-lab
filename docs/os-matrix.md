# Reusable OS matrix

`.github/workflows/os-matrix.yml` runs one test command on Ubuntu, Windows and macOS in parallel
(fail-fast off, 20 minute timeout, one test-log artifact per OS).

## Inputs
| input | default | notes |
|---|---|---|
| `working-directory` | `.` | where install and test run |
| `python-version` | `3.12` | |
| `node-version` | empty | set to install Node |
| `install` | empty | optional shell command (bash) |
| `test` | required | shell command (bash) |
| `os-list` | `["ubuntu-latest","windows-latest","macos-latest"]` | JSON array of runners |

## Calling it from a private product repo
```yaml
name: ci
on: [push, pull_request]
jobs:
  matrix:
    uses: autoscansoftware/platform-lab/.github/workflows/os-matrix.yml@main
    with:
      working-directory: app
      node-version: "20"
      install: npm ci
      test: npm test
```
Pin `@main` to a tag or commit SHA for stability. A private repo may call a reusable workflow from a
public repo without extra settings.

## Cost
Public repos run free. Private repos use paid minutes: Windows counts 2x and macOS 10x, so a
three-OS run of 10 minutes each costs about 130 billed minutes. Limit `os-list` when macOS is not needed.
