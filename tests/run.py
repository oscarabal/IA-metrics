"""Run every suite, each in its own process (the two collectors share module names such as `coach`).

    python tests/run.py            # all suites
    python tests/run.py opencode   # suites whose file name contains "opencode"
"""
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main(argv):
    suites = sorted(glob.glob(os.path.join(HERE, "test_*.py")))
    if argv:
        suites = [s for s in suites if any(a in os.path.basename(s) for a in argv)]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    failed = []
    for s in suites:
        name = os.path.basename(s)
        print("== %s" % name, flush=True)
        r = subprocess.run([sys.executable, s], env=env)
        if r.returncode:
            failed.append(name)
    print("\n%d suites, %d con fallos%s" % (len(suites), len(failed), (": " + ", ".join(failed)) if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
