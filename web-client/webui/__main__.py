import sys

from webui import supervisor

USAGE = "Usage: python -m webui start|stop|restart|status"


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("start", "stop", "restart", "status"):
        print(USAGE)
        sys.exit(1)
    command = sys.argv[1]
    if command == "start":
        sys.exit(0 if supervisor.start() else 1)
    elif command == "stop":
        sys.exit(0 if supervisor.stop() else 1)
    elif command == "restart":
        sys.exit(0 if supervisor.restart() else 1)
    else:
        supervisor.status()


if __name__ == "__main__":
    main()
