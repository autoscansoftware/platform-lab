"""Tiny cross-platform smoke app: prints platform info."""
import platform
import sys


def info():
    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    }


def main():
    for key, value in info().items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
