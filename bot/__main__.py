"""Usage:
  python -m bot collect [--force]
  python -m bot brief morning|midday|close [--force] [--no-collect]
  python -m bot feedback
"""
import sys

from . import briefing, collect, feedback


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    force = "--force" in argv
    cmd = argv[0]
    if cmd == "collect":
        collect.run(force=force)
    elif cmd == "brief" and len(argv) > 1 and argv[1] in briefing.TITLES:
        kind = argv[1]
        if force or briefing.due(kind, briefing.load_yaml("rules.yaml")):
            if "--no-collect" not in argv:
                collect.run(force=True)  # fresh data first
            briefing.build(kind, force=True)
        else:
            print(f"{kind} brief not due now.")
    elif cmd == "feedback":
        feedback.run()
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
