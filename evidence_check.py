"""Does the contract evidence in a database still say what it said? Read-only.

The checks behind certify.py and the nightly backup's restore drill
(backup.verify), each over one company schema on one SQLAlchemy connection.
None of them writes: callers open the connection read-only (read_only()), so
a mistake here is an error, not a change.

  schema_report   the tables, columns, guards and indexes migrations 0028-0031
                  install, present and switched on; the schema's migration
                  version; who this login is, and whether it owns the tables
                  (an owner can switch guards off -- which is what the chain
                  is for).
  reconcile       every revision's terms still hash to its hash; every answer
                  and agreement names the hash it was given; every accepted
                  quote has its answer, account and -- once agreements were
                  being recorded -- its agreement; one accepted amendment per
                  quote; issued revisions belong to their quote.
  audit_chain     the trail's hash chain recomputed from the rows themselves,
                  not from the stored hashes.
  digest          what to write down outside the database: the chain's head
                  and every revision's, answer's and agreement's hash, by id.
                  Hashes and ids only -- nothing about any customer.
  compare         a digest written down earlier against the database now:
                  everything in it still there, unchanged, and the chain grown
                  only by appending.

Each returns a dict with a list of `problems` (strings naming ids, never
customer data); an empty list is a pass.
"""
from sqlalchemy import text

import quote_evidence

EVIDENCE_TABLES = ('commercial_quote', 'commercial_quote_revision', 'commercial_quote_delivery',
                   'commercial_quote_response', 'commercial_agreement', 'email_delivery_event',
                   'contract_audit_event')
INDEXES = ('uq_commercial_quote_one_accepted_amendment', 'uq_contract_audit_event_chain_seq')


def required_triggers():
    """(table, trigger) pairs every company schema must have, switched on."""
    out = [(t, f'{t}_frozen') for t in quote_evidence.FROZEN_TABLES]
    out += [(t, f'{t}_kept') for t in quote_evidence.KEPT_TABLES]
    out += [('commercial_quote', 'commercial_quote_issued_owned'),
            ('contract_audit_event', 'contract_audit_event_chain')]
    return out


def read_only(conn):
    """Make the transaction `conn` is in refuse every write."""
    if conn.dialect.name == 'postgresql':
        conn.execute(text('SET TRANSACTION READ ONLY'))
    return conn


def _q(schema, table):
    return f'"{schema}"."{table}"'


def head_revision():
    import migrate
    from alembic.script import ScriptDirectory
    return ScriptDirectory.from_config(migrate._config()).get_current_head()


def inventory(conn):
    """Company schemas as the database has them, against the company list.
    Returns {'orgs': [...], 'schemas': [...], 'problems': [...]}."""
    import tenancy
    from control_plane import organizations
    from sqlalchemy import select
    schemas = [r[0] for r in conn.execute(text(
        "SELECT nspname FROM pg_namespace WHERE nspname LIKE :p ORDER BY nspname"),
        {'p': tenancy.SCHEMA_PREFIX + '%'})]
    orgs = [dict(r) for r in conn.execute(select(
        organizations.c.slug, organizations.c.schema_name, organizations.c.status,
        organizations.c.is_demo, organizations.c.is_test).order_by(organizations.c.slug)).mappings()]
    have = set(schemas)
    problems = [f'company {o["slug"]} ({o["status"]}) has no schema {o["schema_name"]}'
                for o in orgs if o['schema_name'] not in have and o['status'] not in ('purged',)]
    listed = {o['schema_name'] for o in orgs}
    strays = [s for s in schemas if s not in listed and not s.endswith('__next')]
    return {'orgs': orgs, 'schemas': schemas, 'unlisted_schemas': strays, 'problems': problems}


def schema_report(conn, schema):
    out = {'schema': schema, 'problems': []}
    p = out['problems']
    out['version'] = None
    if conn.execute(text('SELECT to_regclass(:t)'), {'t': _q(schema, 'alembic_version')}).scalar():
        out['version'] = conn.execute(text(
            f'SELECT version_num FROM {_q(schema, "alembic_version")}')).scalar()
    head = head_revision()
    out['head'] = head
    if out['version'] != head:
        p.append(f'migration version {out["version"]}, expected {head}')
    import models  # noqa: F401  (registers the tables on db.metadata)
    from extensions import db
    cols = {}
    for table, column in conn.execute(text(
            'SELECT table_name, column_name FROM information_schema.columns '
            'WHERE table_schema = :s'), {'s': schema}):
        cols.setdefault(table, set()).add(column)
    for table in EVIDENCE_TABLES:
        if table not in cols:
            p.append(f'table {table} is missing')
            continue
        model = db.metadata.tables.get(table)
        for c in (model.columns if model is not None else []):
            if c.name not in cols[table]:
                p.append(f'column {table}.{c.name} is missing')
    triggers = {(t, n): e for t, n, e in conn.execute(text(
        'SELECT c.relname, t.tgname, t.tgenabled FROM pg_trigger t '
        'JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace '
        'WHERE n.nspname = :s AND NOT t.tgisinternal'), {'s': schema})}
    for key in required_triggers():
        if key not in triggers:
            p.append(f'guard {key[1]} on {key[0]} is missing')
        elif triggers[key] == 'D':
            p.append(f'guard {key[1]} on {key[0]} is switched off')
    indexes = {r[0] for r in conn.execute(text(
        'SELECT indexname FROM pg_indexes WHERE schemaname = :s'), {'s': schema})}
    for name in INDEXES:
        if name not in indexes:
            p.append(f'index {name} is missing')
    who = conn.execute(text(
        'SELECT current_user, r.rolsuper FROM pg_roles r WHERE r.rolname = current_user')).first()
    owner = conn.execute(text(
        'SELECT tableowner FROM pg_tables WHERE schemaname = :s AND tablename = :t'),
        {'s': schema, 't': 'contract_audit_event'}).scalar()
    out['login'] = {'user': who[0] if who else None, 'superuser': bool(who and who[1]),
                    'owns_evidence_tables': bool(who and owner == who[0])}
    # The chain hashes with the built-in sha256(), PostgreSQL 11 and later.
    out['server_version'] = conn.execute(text('SHOW server_version')).scalar()
    return out


def _rows(conn, schema, sql, **params):
    return conn.execute(text(sql.format(s=f'"{schema}".')), params).mappings().all()


def reconcile(conn, schema):
    out = {'schema': schema, 'problems': [], 'exceptions': [], 'counts': {}, 'tampered': []}
    p, ex, n, t = out['problems'], out['exceptions'], out['counts'], out['tampered']

    def changed(msg):
        # A hash that no longer matches is a change to evidence, not a loose
        # end: the backup refuses to call such a database good (backup.py).
        p.append(msg)
        t.append(msg)
    revs = {r['id']: r for r in _rows(conn, schema,
            'SELECT id, quote_id, terms, content_hash FROM {s}commercial_quote_revision')}
    n['revisions'] = len(revs)
    for r in revs.values():
        if quote_evidence.digest(r['terms']) != r['content_hash']:
            changed(f'revision {r["id"]}: its terms no longer hash to its hash')
    quotes = {q['id']: q for q in _rows(conn, schema,
              'SELECT id, status, account_id, issued_revision_id, amends_quote_id, amends_agreement_id '
              'FROM {s}commercial_quote')}
    n['quotes'] = len(quotes)
    for q in quotes.values():
        rid = q['issued_revision_id']
        if rid is not None and (rid not in revs or revs[rid]['quote_id'] != q['id']):
            p.append(f'quote {q["id"]}: bound to revision {rid}, which is not one of its own')
    responses = {r['quote_id']: r for r in _rows(conn, schema,
                 'SELECT id, quote_id, revision_id, content_hash, decision, account_id, created_at '
                 'FROM {s}commercial_quote_response')}
    n['responses'] = len(responses)
    for r in responses.values():
        rev = revs.get(r['revision_id'])
        if rev is None or rev['quote_id'] != r['quote_id']:
            p.append(f'answer {r["id"]}: names revision {r["revision_id"]}, not one of quote {r["quote_id"]}\'s')
        elif rev['content_hash'] != r['content_hash']:
            changed(f'answer {r["id"]}: its hash is not its revision\'s')
    agreements = {a['quote_id']: a for a in _rows(conn, schema,
                  'SELECT id, quote_id, revision_id, response_id, account_id, content_hash, '
                  'amends_agreement_id, created_at FROM {s}commercial_agreement')}
    n['agreements'] = len(agreements)
    accounts = {a['id'] for a in _rows(conn, schema, 'SELECT id FROM {s}commercial_account')}
    by_id = {a['id']: a for a in agreements.values()}
    first_agreement = min((a['created_at'] for a in agreements.values() if a['created_at']), default=None)
    for a in agreements.values():
        rev, resp, q = revs.get(a['revision_id']), responses.get(a['quote_id']), quotes.get(a['quote_id'])
        if rev is None or rev['content_hash'] != a['content_hash']:
            changed(f'agreement {a["id"]}: its hash is not its revision\'s')
        if resp is None or resp['id'] != a['response_id'] or resp['decision'] != 'accepted':
            p.append(f'agreement {a["id"]}: not backed by its quote\'s acceptance')
        if q is None or q['status'] != 'accepted':
            p.append(f'agreement {a["id"]}: its quote is not accepted')
        if a['account_id'] not in accounts:
            p.append(f'agreement {a["id"]}: account {a["account_id"]} does not exist')
        if a['amends_agreement_id'] is not None and a['amends_agreement_id'] not in by_id:
            p.append(f'agreement {a["id"]}: amends agreement {a["amends_agreement_id"]}, which does not exist')
    accepted = [q for q in quotes.values() if q['status'] == 'accepted']
    n['accepted_quotes'] = len(accepted)
    successors = {}
    for q in accepted:
        resp = responses.get(q['id'])
        if resp is None or resp['decision'] != 'accepted':
            p.append(f'quote {q["id"]}: accepted with no acceptance recorded')
            continue
        if q['account_id'] not in accounts:
            p.append(f'quote {q["id"]}: accepted with no account behind it')
        if q['id'] not in agreements:
            # Quotes accepted before agreements were recorded (migration 0030)
            # have only their answer. One accepted after the first agreement
            # was written should have had its own.
            if first_agreement is not None and resp['created_at'] and resp['created_at'] > first_agreement:
                p.append(f'quote {q["id"]}: accepted after agreements began, with no agreement')
            else:
                ex.append(f'quote {q["id"]}: accepted before agreements were recorded; its answer is its record')
        if q['amends_quote_id']:
            successors.setdefault(q['amends_quote_id'], []).append(q['id'])
    for original, later in successors.items():
        if len(later) > 1:
            p.append(f'quote {original}: {len(later)} accepted amendments ({sorted(later)})')
    return out


def audit_chain(conn, schema):
    """Recompute the chain from the rows. Returns head (seq, hash) and the
    first place it breaks, if it does."""
    out = {'schema': schema, 'problems': [], 'length': 0, 'head': None}
    rows = _rows(conn, schema, 'SELECT * FROM {s}contract_audit_event ORDER BY chain_seq NULLS FIRST, id')
    prev, seq = quote_evidence.AUDIT_GENESIS, 0
    for r in rows:
        if r['chain_seq'] is None:
            out['problems'].append(f'audit row {r["id"]} is not in the chain')
            continue
        seq += 1
        if r['chain_seq'] != seq:
            out['problems'].append(f'audit chain jumps from {seq - 1} to {r["chain_seq"]} at row {r["id"]}')
            seq = r['chain_seq']
        if r['prev_hash'] != prev:
            out['problems'].append(f'audit row {r["id"]} (#{seq}) does not follow #{seq - 1}')
        if quote_evidence.audit_row_hash(r, r['chain_seq'], r['prev_hash']) != r['row_hash']:
            out['problems'].append(f'audit row {r["id"]} (#{seq}) has been changed since it was written')
        prev = r['row_hash']
    out['length'] = seq
    out['head'] = {'seq': seq, 'hash': prev} if seq else None
    return out


def digest(conn, schema):
    """What the backup writes down: hashes and ids, nothing else."""
    chain = audit_chain(conn, schema)
    return {
        'audit_head': chain['head'],
        'revisions': {str(r['id']): r['content_hash'] for r in _rows(
            conn, schema, 'SELECT id, content_hash FROM {s}commercial_quote_revision')},
        'responses': {str(r['id']): [r['quote_id'], r['content_hash'], r['decision']] for r in _rows(
            conn, schema, 'SELECT id, quote_id, content_hash, decision FROM {s}commercial_quote_response')},
        'agreements': {str(r['id']): [r['quote_id'], r['content_hash']] for r in _rows(
            conn, schema, 'SELECT id, quote_id, content_hash FROM {s}commercial_agreement')},
    }


def compare(conn, schema, then):
    """A digest taken earlier (`then`) against the database now."""
    out = {'schema': schema, 'problems': []}
    p = out['problems']
    now = digest(conn, schema)
    for kind in ('revisions', 'responses', 'agreements'):
        for key, value in (then.get(kind) or {}).items():
            have = now[kind].get(key)
            if have is None:
                p.append(f'{kind[:-1]} {key} is gone')
            elif have != value:
                p.append(f'{kind[:-1]} {key} has changed')
    head = then.get('audit_head')
    if head:
        row = conn.execute(text(
            f'SELECT row_hash FROM {_q(schema, "contract_audit_event")} WHERE chain_seq = :n'),
            {'n': head['seq']}).scalar()
        if row != head['hash']:
            p.append(f'audit chain #{head["seq"]} is no longer what was written down')
    p += audit_chain(conn, schema)['problems']
    return out
