"""Run every test suite, the way release.py does, and fail if any fails.

    TEST_POSTGRES_URL=postgresql://... python tests/run_all.py

Each suite runs in its own process: many set environment variables and build
their own app at import time, so sharing one interpreter would let one suite's
settings leak into the next. Style is detected per file (release._is_pytest_style).
"""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import release  # noqa: E402

PER_SUITE_SECONDS = 900


def main():
    suites = sorted((ROOT / 'tests').glob('test_*.py'))
    failed = []
    started = time.time()
    for path in suites:
        cmd = ([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', str(path)]
               if release._is_pytest_style(path) else [sys.executable, str(path)])
        t0 = time.time()
        try:
            r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                               timeout=PER_SUITE_SECONDS)
            ok, out = r.returncode == 0, r.stdout + r.stderr
        except subprocess.TimeoutExpired as e:
            ok, out = False, f'TIMED OUT after {PER_SUITE_SECONDS}s\n{e.stdout or ""}'
        print(f'{"✅" if ok else "❌"} {path.name} ({time.time() - t0:.0f}s)', flush=True)
        if not ok:
            failed.append(path.name)
            tail = '\n'.join(out.strip().splitlines()[-40:])
            print(f'::group::{path.name} output\n{tail}\n::endgroup::', flush=True)
    summary = (f'{len(suites) - len(failed)}/{len(suites)} suites passed '
               f'in {(time.time() - started) / 60:.0f} min')
    print(f'\n{summary}')
    # On GitHub Actions the database service's shutdown log follows this and
    # buries it, so the result also goes where it is read: the job summary,
    # and one annotation per failing suite on the check itself.
    step_summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if step_summary:
        with open(step_summary, 'a') as fh:
            fh.write(f'### {summary}\n\n')
            for name in failed:
                fh.write(f'- ❌ `{name}`\n')
    for name in failed:
        print(f'::error title=Test suite failed::{name}')
    if failed:
        print('Failed: ' + ', '.join(failed))
        sys.exit(1)


if __name__ == '__main__':
    main()
