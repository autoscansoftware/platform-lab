# labctl

Run several containers ("lanes") on one rented VM pod over ssh. Python 3.11+, standard library only.
labctl never calls a cloud API: renting and destroying the pod is the operator's job.

## Config

JSON file at `$LABCTL_CONFIG` (default `~/.labctl.json`, keep it outside the repo):

```json
{"host": "pod.example", "port": 22, "user": "root", "identity_file": "~/.ssh/id_lab",
 "remote_root": "/workspace/lab", "self_destruct_hours": 4, "destroy_cmd": "operator-side command"}
```

## Verbs

- `lanes up <n> [--image IMG] [--gpu]`: start lane-1..n; CPU and RAM split evenly, GPU shared with `--gpu`. Arms the self-destruct timer on the pod.
- `lanes ls`, `lanes down <name>|--all`
- `run <lane> -- <cmd>`: nohup inside the container, prints a job id. `wait <job>`, `logs <job> -n N`
- `push <local> <rel>`, `pull <rel> <local>`: tar over ssh, byte and file count verified. Remote paths are relative to `remote_root`; absolute paths and `..` are refused.
- `status`: GPU, disk, lanes, jobs, minutes to self-destruct. `extend <hours>` adds time (max 12 h total).
- `tunnel <lane>`: prints the `ssh -L` command for the lane's noVNC port (127.0.0.1 only).

## Self-destruct

A timer on the pod stops all lanes at the deadline. If `destroy_cmd` is set in the config, it also leaves a
`DESTROY_MARKER` file in the remote root for the operator's watcher to act on.

## Tests

`python -m unittest discover -s labctl/tests`
