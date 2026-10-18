"""Nana knows how Akye works, says hello on the dashboard, and can listen.

- "How does hiring work?" is answered from the help guide, never from memory,
  and comes with a button to the page it is done on.
- A question the guide does not cover gets "not sure", not a guess.
- The business's own FAQ entries are found too.
- Every link in the guide is a real page.
- The welcome pop-up shows on the dashboard only while setup is unfinished,
  and only when the setup chat is switched on.
- The setup chat opens focused the first time, and has a mic and read-aloud.
"""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/help.db'
os.environ['SECRET_KEY'] = 'test'
os.environ.pop('ANTHROPIC_API_KEY', None)
os.environ.pop('OPENROUTER_API_KEY', None)
sys.path.insert(0, ROOT)

from app import create_app
from extensions import db
from models import BusinessSetting, Faq
import help_guide, help_topics, assistant, agent, llm, setup_assistant

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


def owner():
    c = app.test_client()
    with c.session_transaction() as s:
        s['logged_in'] = True
        s['role'] = 'owner'
    return c


with app.app_context():
    db.create_all()
    BusinessSetting.set('business_name', 'Sparkle Co')
    db.session.commit()

print('\n1. The guide is sound')
rules = {r.rule.rstrip('/') for r in app.url_map.iter_rules() if 'GET' in r.methods}
keys = [t['key'] for t in help_topics.TOPICS]
check(len(keys) >= 20, f'{len(keys)} topics')
check(len(keys) == len(set(keys)), 'every topic key is unique')
bad = [t['link'] for t in help_topics.TOPICS if t.get('link') and t['link'][1].rstrip('/') not in rules]
check(not bad, f'every link is a real page {bad or ""}')
check(all('**' not in t['answer'] for t in help_topics.TOPICS), 'no markdown in answers')

print('\n2. Owners\' words find the right topic')
with app.app_context():
    for q, must in [('how does hiring work', 'hir'),
                    ('how do I change my prices', 'pric'),
                    ('where is my booking page link', 'book')]:
        found = help_guide.search(q)
        check(found and must in (found[0]['title'] + ' '.join(found[0]['keywords'])).lower(),
              f'"{q}" → {found[0]["title"] if found else "nothing"}')
    text, link = help_guide.answer('xyzzy plugh')
    check(link is None and 'not sure' in text, 'no match says "not sure" rather than guessing')

with app.app_context():
    db.session.add(Faq(question='Why did my cleaner not get the job text?',
                       answer='Check their cell number is saved on their team page.'))
    db.session.commit()
    found = help_guide.search('cleaner did not get the job text')
    check(any(t['key'].startswith('faq-') for t in found), 'the business\'s own FAQ is searched')

print('\n3. Nana uses the guide, and hands back the page')
os.environ['ANTHROPIC_API_KEY'] = 'sk-ant-test'
SCRIPT, SENT = [], []
def fake_post(body, timeout=30):
    SENT.append(body)
    return SCRIPT.pop(0)
llm.post = fake_post
with app.app_context(), app.test_request_context():
    SCRIPT[:] = [{'content': [{'type': 'tool_use', 'id': 'h', 'name': 'how_to',
                               'input': {'question': 'how does hiring work'}}],
                  'stop_reason': 'tool_use'},
                 {'content': [{'type': 'text', 'text': 'Applicants apply from your hiring link and you review them.'}],
                  'stop_reason': 'end_turn'}]
    out = agent.run('how does hiring work?')
fed = SENT[-1]['messages'][-1]['content'][0]['content']
check('help guide' in fed, 'the guide text was handed to Claude')
check(out.get('link') and out['link']['href'].startswith('/'), 'answer comes with a page button')
check('how_to' in SENT[0]['system'][0]['text'], 'the prompt sends how-to questions to the guide')

with app.test_request_context():
    text, card = setup_assistant.tool_how_to('how do I change my prices')
check(card and card['kind'] == 'link', 'the setup chat gets the same answer and a button')

print('\n4. The welcome pop-up')
c = owner()
r = c.get('/')
dash = r.data if r.status_code == 200 else c.get('/dashboard').data
check(b'nanawelcome' in dash, 'shown on the dashboard while setup is unfinished')
check(b'focus=1' in dash, 'and it opens the setup chat')
r = c.get('/settings/pricing')
check(b'nanawelcome' not in r.data, 'not on other pages')
check(b'Finish with Nana' in r.data, 'other pages\' nudge offers Nana instead')
os.environ.pop('ANTHROPIC_API_KEY')
r = c.get('/')
dash = r.data if r.status_code == 200 else c.get('/dashboard').data
check(b'nanawelcome' not in dash, 'no pop-up when the chat is off')
os.environ['ANTHROPIC_API_KEY'] = 'sk-ant-test'

print('\n5. The setup chat: focused first, mic and read-aloud')
r = c.get('/settings/getting-started')
check(b'card sa-card sa-focus' in r.data, 'first visit opens as a focused window')
check(b'id="sa-mic"' in r.data and b'id="sa-speak"' in r.data, 'mic and read-aloud are there')
check(b'nana-speak' in r.data, 'read-aloud choice is shared with Nana\'s page')
with app.test_request_context():
    from flask import session
    session['role'] = 'owner'
    setup_assistant.save_chat([{'role': 'assistant', 'content': 'hi'},
                               {'role': 'user', 'content': '180'},
                               {'role': 'assistant', 'content': 'ok'}])
r = c.get('/settings/getting-started')
check(b'card sa-card sa-focus' not in r.data, 'after they have talked to her, it sits on the page')
r = c.get('/settings/getting-started?focus=1')
check(b'card sa-card sa-focus' in r.data, 'the pop-up\'s button opens it focused again')

if failures:
    print(f'\n❌ {len(failures)} check(s) failed')
    sys.exit(1)
print('\n✅ All help, welcome and voice tests passed.')
