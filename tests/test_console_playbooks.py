"""Playbooks: reference material that is the product's own, not any one
company's -- the same reasoning that already put `feedback` and `console_users`
in the control plane rather than a tenant schema (see control_plane.py).

The interesting parts: it is gated by the same rules as everything else in the
console (a helper can read, only a manager+ can write), and the content is
stored and shown as plain text -- deliberately no markdown renderer added for
a page only people already inside the console ever see.
"""
import os, sys

# console_docs lives in the control plane's `public` Postgres schema, the same
# as console_users and organizations -- SQLite has no notion of that schema,
# so this needs the real thing, same as test_console_nana_proposals.py.
os.environ['DATABASE_URL'] = os.environ.get(
    'TEST_POSTGRES_URL', 'postgresql://app_user:localtest@127.0.0.1:5432/postgres')
os.environ['SECRET_KEY'] = 'test'
os.environ['BASE_DOMAIN'] = 'akye.test'
os.environ['FLASK_ENV'] = 'development'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


print('\n1. The table lives in the control plane, not a tenant schema')
cp = open(os.path.join(ROOT, 'control_plane.py')).read()
check("console_docs = Table(" in cp, 'console_docs is declared on control_metadata')
check('console_docs' in cp[cp.index('def ensure_table'):cp.index('def ensure_table') + 400],
      'and ensure_table() actually creates it')

print('\n2. Round-trip through the real helpers, on real disposable Postgres')
import secrets
import control_plane as cp_mod
import provisioning
engine = provisioning._engine()
cp_mod.ensure_table(engine)

marker = 'Growth Program ' + secrets.token_hex(4)
before = len(cp_mod.all_console_docs(engine))
doc_id = cp_mod.add_console_doc(engine, marker, 'week 1: warm outreach',
                                created_by='owner@example.com', sort_order=0)
check(doc_id is not None, 'add_console_doc returns the new row id')
rows = cp_mod.all_console_docs(engine)
check(len(rows) == before + 1, 'and it shows up in the list -- one more than before')
check(any(r['title'] == marker for r in rows), 'under the title it was given')
got = cp_mod.console_doc(engine, doc_id)
check(got is not None and got['content'] == 'week 1: warm outreach',
      'fetched by id, content intact')
cp_mod.update_console_doc(engine, doc_id, marker + ' v2', 'week 1: revised')
got = cp_mod.console_doc(engine, doc_id)
check(got['title'] == marker + ' v2' and got['content'] == 'week 1: revised',
      'editing replaces title and content in place')
missing_id = max((r['id'] for r in rows), default=0) + 1000
check(cp_mod.console_doc(engine, missing_id) is None,
      'a missing id returns nothing rather than raising')

# Leave the table as this run found it -- a shared Postgres instance, not a
# throwaway per-test database.
from sqlalchemy import delete
with engine.begin() as conn:
    conn.execute(delete(cp_mod.console_docs).where(cp_mod.console_docs.c.id == doc_id))

print('\n3. Reachable only through the console\'s own gate, same as People')
src = open(os.path.join(ROOT, 'blueprints', 'console.py')).read()
for route in ('playbooks', 'playbook_view', 'playbook_new', 'playbook_edit'):
    seg = src[src.index(f'def {route}') - 200:src.index(f'def {route}')]
    check('@console_required' in seg, f'{route} requires a console session')
for route in ('playbook_new', 'playbook_edit'):
    seg = src[src.index(f'def {route}') - 260:src.index(f'def {route}')]
    check('@can_manage' in seg, f'{route} is behind the same gate as add_person')
# A helper can read but the page hides the write buttons -- checked server-side,
# not just left to the template, the same courtesy/permission split as People.
check("control_plane.rank(request.console_user['role'])" in src
      and "rank('manager')" in src,
      'read-only view for a helper is computed server-side, not template-only')

print('\n4. Plain text in, plain text out -- no markdown renderer smuggled in')
check('import markdown' not in src and 'mistune' not in src,
      'no markdown dependency was added for this')
view = open(os.path.join(ROOT, 'templates', 'console', 'playbook_view.html')).read()
check('<pre class="con-body"' in view,
      'content renders pre-wrapped, the same choice SOP.content already made')
check('|safe' not in view,
      'and it is never marked safe -- stored content is escaped like any other')

print('\n5. Seed script is idempotent and writes through the same helpers')
seed = open(os.path.join(ROOT, 'seed_growth_playbook.py')).read()
check('control_plane.all_console_docs(engine)' in seed,
      'it checks what is already there before writing')
check('if title in existing' in seed, 'and skips a title that already exists')
check('control_plane.add_console_doc(' in seed,
      'writes go through the real helper, not a raw insert')

print()
if failures:
    print(f'❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    sys.exit(1)
print('✅ Playbooks are stored in the control plane and gated like everything else in the console.')
