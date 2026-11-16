import os
import subprocess
import sys


def main() -> None:
    subprocess.check_call([sys.executable, "manage.py", "migrate", "--noinput"])
    subprocess.check_call([sys.executable, "manage.py", "collectstatic", "--noinput"])
    subprocess.check_call([sys.executable, "manage.py", "seed", "--skip-if-exists"])
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
