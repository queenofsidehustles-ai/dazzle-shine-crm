"""Playbook steps as checkboxes, ticked in the console and saved for everyone.

A step is written "[ ]" or "[x]" at the start of a line. The console shows it
as a checkbox; ticking one rewrites that one line of the playbook, so the
whole team sees the same progress. The ways this could go wrong:

  * a tick landing on the wrong step (a checkbox's position and the text's
    steps disagreeing, or the playbook edited since the page loaded);
  * somebody who may only read the playbooks changing it by ticking;
  * a tick sent from another site.
"""
import os
import secrets
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


os.environ.setdefault('SECRET_KEY', 'checkbox-test')
import blueprints.console as cm
import seed_growth_playbook as seed

print('\n1. Steps become checkboxes, numbered in the order they are written')
text = ('## Day 1\n\n1. [ ] Lock the offer\n2. [x] Make the links\n\n'
        '- [ ] A bullet step\n\nNot a step: see [ ] later.\n\n'
        '[ ] Printed-checklist style\n[x] Another\n')
out = cm._render_playbook(text, tickable=True)
boxes = out.count('class="pb-box"')
check(boxes == 5, f'5 checkboxes ({boxes})')
check(all(f'data-task="{i}"' in out for i in range(5)), 'numbered 0–4')
check(out.count(' checked') == 2, 'the two [x] steps are ticked')
check(out.count('<li class="pb-task done">') == 1 and out.count('<li class="pb-task">') == 2,
      'list steps get a class the page styles (done ones struck through)')
check('see [ ] later' in out, 'a bracket in the middle of a sentence is left alone')
ro = cm._render_playbook(text, tickable=False)
check(ro.count(' disabled') == 5 and 'data-task' not in ro,
      'for someone who may not edit, the boxes show but cannot be ticked')
check(cm._render_playbook('- [ ] <script>x</script>', tickable=True).count('<script>') == 0,
      'a step is still escaped')

code = cm._render_playbook('Link: `a.com/?x=1&y=2` and `<b>` and <i>', tickable=False)
check('<code>a.com/?x=1&amp;y=2</code>' in code, 'an "&" inside code shows as "&", not "&amp;"')
check('<code>&lt;b&gt;</code>' in code and '&lt;i&gt;' in code and '<b>' not in code
      and '<i>' not in code, 'and a tag, in code or not, is still shown as text')

print('\n2. A tick changes exactly one line')
t = cm._set_task(text, 1, False)
check(t == text.replace('2. [x] Make', '2. [ ] Make'), 'unticking step 2 changes only step 2')
t = cm._set_task(text, 4, False)
check(t == text.replace('[x] Another', '[ ] Another'), 'the printed-checklist style works too')
check(cm._set_task(text, 9, True) is None, 'a step that does not exist: nothing')

print('\n3. The Week 1 playbook is a checklist')
W1 = 'Week 1 — Prep & Warm Activation'
week1 = dict(seed.DOCS)[W1].strip()
out = cm._render_playbook(week1, tickable=True)
steps = len(cm._TASK_LINE.findall(week1))
check(steps >= 30 and out.count('data-task=') == steps,
      f'every one of its {steps} steps is a working checkbox')
check(week1.count('**Done when:**') >= 2, '"Done when" lines stand out')

print('\n4. The seed brings an untouched old Week 1 up to date, and nothing else')
check(seed._fingerprint(week1) not in seed.UNTOUCHED[W1], 'the new version is not in the old list')


def postgres_url():
    from sqlalchemy import create_engine, text as sql
    for candidate in (os.environ.get('TEST_POSTGRES_URL'),
                      'postgresql://app_user:localtest@127.0.0.1:5432/postgres'):
        if not candidate:
            continue
        try:
            with create_engine(candidate).connect() as c:
                c.execute(sql('SELECT 1'))
            return candidate
        except Exception:
            continue
    return None


PG = postgres_url()
if not PG:
    print('\n  ⚠️  SKIPPED the console half: no PostgreSQL server found.')
else:
    from sqlalchemy import create_engine, text as sql
    DB = 'dsm_playbook_checkbox_test'
    admin = create_engine(PG, isolation_level='AUTOCOMMIT')
    with admin.connect() as conn:
        conn.execute(sql(f'DROP DATABASE IF EXISTS {DB} WITH (FORCE)'))
        conn.execute(sql(f'CREATE DATABASE {DB}'))
    os.environ.update(DATABASE_URL=f'{PG.rsplit("/", 1)[0]}/{DB}', BASE_DOMAIN='akyehq.test')
    import notifications
    notifications.send_email = lambda *a, **k: (True, 'stub')
    from app import create_app
    import control_plane
    import provisioning
    app = create_app()
    try:
        with app.app_context():
            eng = provisioning._engine()
            control_plane.ensure_table(eng)
            # The first Week 1 version, exactly as PR #36 seeded it, plus a hand-edited copy.
            import subprocess
            old = subprocess.run(['git', 'show', '98f70b6:seed_growth_playbook.py'], cwd=ROOT,
                                 capture_output=True, text=True).stdout
            ns = {}
            if old:
                exec(compile(old.replace('import control_plane\nimport provisioning\n', ''),
                             'old_seed', 'exec'), ns)
            first = dict(ns['DOCS'])[W1].strip() if ns else None
            if first:
                check(seed._fingerprint(first) in seed.UNTOUCHED[W1],
                      'the fingerprint matches the version PR #36 seeded')
                control_plane.add_console_doc(eng, W1, first, created_by='seed script', sort_order=2)
            edited_title = 'Growth Program — Overview & Strategy'
            control_plane.add_console_doc(eng, edited_title, 'hand-edited', sort_order=0)
            seed.main()
            docs = {d['title']: d for d in control_plane.all_console_docs(eng)}
            if first:
                check(docs[W1]['content'] == week1, 'an untouched first version is updated')
            check(docs[edited_title]['content'] == 'hand-edited', 'a hand-edited playbook is left alone')
            before = docs[W1]['content']
            seed.main()
            check(control_plane.all_console_docs(eng) and
                  {d['title']: d for d in control_plane.all_console_docs(eng)}[W1]['content'] == before,
                  'running it again changes nothing')
            doc_id = docs[W1]['id']
            TAG = secrets.token_hex(3)
            for role in ('manager', 'helper'):
                control_plane.add_console_user(eng, f'{role}-{TAG}@x.test', role,
                                               'a-real-console-password-1', role=role)

        def signed_in(role):
            c = app.test_client()
            c.post('/console/login', data={'email': f'{role}-{TAG}@x.test',
                                          'password': 'a-real-console-password-1'})
            return c

        print('\n5. Ticking in the console saves it for everyone')
        m = signed_in('manager')
        page = m.get(f'/console/playbooks/{doc_id}').data.decode()
        check('data-task="0"' in page and 'data-rev="' in page, 'a manager sees tickable boxes')
        rev = page.split('data-rev="')[1].split('"')[0]
        r = m.post(f'/console/playbooks/{doc_id}/task', data={'index': 0, 'done': '1', 'rev': rev})
        j = r.get_json()
        check(r.status_code == 200 and j['ok'] and j['rev'] != rev, 'the tick is saved')
        with app.app_context():
            saved = control_plane.console_doc(eng, doc_id)['content']
        check(saved == cm._set_task(before, 0, True), 'exactly the first step is ticked in the text')
        r = m.post(f'/console/playbooks/{doc_id}/task', data={'index': 0, 'done': '1', 'rev': rev})
        check(r.status_code == 409, 'a tick from a page that is out of date is refused')
        r = m.post(f'/console/playbooks/{doc_id}/task', data={'index': 999, 'done': '1', 'rev': j['rev']})
        check(r.status_code == 400, 'a step that is not there is refused')
        r = m.post(f'/console/playbooks/{doc_id}/task', data={'index': 1, 'done': '1', 'rev': j['rev']},
                   headers={'Origin': 'https://evil.example'})
        check(r.status_code == 403, 'a tick sent from another site is refused')
        page = signed_in('manager').get(f'/console/playbooks/{doc_id}').data.decode()
        check('data-task="0" checked' in page, 'another person opening it sees the tick')

        print('\n6. Someone who may only read cannot tick')
        h = signed_in('helper')
        page = h.get(f'/console/playbooks/{doc_id}').data.decode()
        check('data-task=' not in page and ' disabled' in page, 'a helper sees boxes that cannot be ticked')
        r = h.post(f'/console/playbooks/{doc_id}/task', data={'index': 1, 'done': '1', 'rev': rev})
        check(r.status_code == 403, 'and a tick sent anyway is refused')
        with app.app_context():
            logged = control_plane.console_log_all(eng)
        check(any(x['action'] == 'ticked a step' and x['actor'] == f'manager-{TAG}@x.test'
                  for x in logged), 'the record says who ticked what')
    finally:
        try:
            from extensions import db
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
            provisioning._engine().dispose()
        except Exception:
            pass
        with admin.connect() as conn:
            conn.execute(sql(f'DROP DATABASE IF EXISTS {DB} WITH (FORCE)'))

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ Playbook steps are checkboxes, and a tick lands on the right step, for everyone.')
