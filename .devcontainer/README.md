# Dev container / Codespace

Opens with Python 3.12, Postgres 16 (same credentials as CI), `gh`, and the
environment variables the test suites read (`TEST_POSTGRES_URL`, `PGURL`,
`PGOPTIONS`). `setup.sh` builds `.venv`, installs `requirements.txt`, fetches
every branch and tag, and checks that Postgres answers.

Running a release from here (see RELEASING.md):

    gh auth status                        # logged in, so the checks are read from GitHub
    git checkout main && git pull
    .venv/bin/python release.py --akye            # preview, changes nothing
    .venv/bin/python release.py --akye --go       # every suite, then tag and promote

The test run takes about 20-30 minutes. Run it in `tmux` or raise the
Codespace idle timeout; nothing is pushed until it passes.
