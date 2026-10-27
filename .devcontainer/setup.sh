#!/usr/bin/env bash
# Runs once when the container is created. Safe to run again.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Python: $(python3 --version)"

if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt

# test_release.py runs release.py against the other branches and tags, so a
# Codespace's single-branch checkout is not enough. `git fetch --all` means
# "every remote", not "every branch": it still obeys a single-branch refspec,
# so widen the refspec to every branch and fetch that explicitly.
git config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
git fetch origin '+refs/heads/*:refs/remotes/origin/*' --tags --quiet \
  || echo "git fetch failed; run it again once you are signed in"

# Wait for Postgres, then say plainly whether the suites can run.
.venv/bin/python - <<'PY'
import os, sys, time
import psycopg2
url = os.environ.get("TEST_POSTGRES_URL", "").replace("postgresql+psycopg2://", "postgresql://")
for _ in range(30):
    try:
        psycopg2.connect(url).close()
        print("Postgres is up:", url.split("@")[-1])
        sys.exit(0)
    except Exception:
        time.sleep(2)
print("Postgres did not come up; the test suites need it.")
sys.exit(1)
PY

cat <<'MSG'

Ready. To run the whole test suite:   .venv/bin/python tests/run_all.py --jobs auto
To preview a release:                 .venv/bin/python release.py --akye
To release (you must be on main):     .venv/bin/python release.py --akye --go
MSG
