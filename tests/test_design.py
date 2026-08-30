"""The design system holds together.

The product used to carry 2,400 hand-picked colour literals across 186 shades,
which is what made it look assembled rather than designed. They are now tokens
in `static/akye.css`. These tests exist because the sweep that did that had two
failure modes which are invisible until somebody looks at the right screen:

  * a token in a place that cannot resolve one -- a `theme-color` meta tag, a
    canvas `fillStyle`, a Chart.js colour. CSS custom properties only mean
    something to the CSS engine. Assigned anywhere else they are silently
    ignored, and a chart renders black or a page renders with no colour at all.

  * a token in a page that never loaded the stylesheet defining it, which
    resolves to nothing -- white text on white, on the cleaner's phone.

Both were real. The chart one was one command away from being deployed.
"""
import pathlib, re, sys, collections

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / 'templates'
CSS = ROOT / 'static' / 'akye.css'

failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


def templates():
    return sorted(TEMPLATES.rglob('*.html'))


def parent_of(p):
    m = re.search(r'{%\s*extends\s+"([^"]+)"', p.read_text(errors='replace'))
    return TEMPLATES / m.group(1) if m else None


def loads_design_system(p):
    """True if this page gets akye.css, directly or from a template it extends."""
    seen = set()
    cur = p
    while cur is not None and cur not in seen:
        seen.add(cur)
        if not cur.exists():
            return False
        if 'akye.css' in cur.read_text(errors='replace'):
            return True
        cur = parent_of(cur)
    return False


print('\n1. The stylesheet itself defines the palette')
css = CSS.read_text()
for tok in ('--amber', '--ink', '--muted', '--line', '--ground', '--good',
            '--warn', '--info', '--surface', '--softer'):
    check(f'{tok}:' in css, f'{tok} is defined')


print('\n2. No token is used where a token cannot resolve')
# A meta tag, an SVG paint attribute or a bare colour attribute is read by
# something other than the CSS engine. `var(--x)` there is simply invalid.
NON_CSS_ATTR = re.compile(
    r'\b(?:content|fill|stroke|bgcolor|color|media)\s*=\s*"[^"]*var\(--')
offenders = []
for p in templates():
    for i, line in enumerate(p.read_text(errors='replace').split('\n'), 1):
        if 'style=' in line:
            continue                       # a style attribute IS css
        if NON_CSS_ATTR.search(line):
            offenders.append(f'{p.relative_to(ROOT)}:{i}')
check(not offenders, f'no CSS variable in a non-CSS attribute ({offenders[:3]})')


print('\n3. No token is handed to a canvas or a chart')
# This is the one that nearly shipped: `backgroundColor: 'var(--amber)'` in a
# Chart.js dataset draws nothing. Resolve it with getComputedStyle first.
CANVAS = re.compile(
    r'\b(?:fillStyle|strokeStyle|backgroundColor|borderColor|pointBackgroundColor|'
    r'shadowColor|hoverBackgroundColor)\s*[:=]\s*[\'"]var\(--')
offenders = []
for p in templates():
    text = p.read_text(errors='replace')
    for block in re.findall(r'<script[^>]*>(.*?)</script>', text, re.S):
        for line in block.split('\n'):
            # `el.style.borderColor = 'var(--amber)'` is fine -- an inline style
            # IS the CSS engine, and the variable resolves there. What breaks is
            # the same word as a plain object key in a chart config, or on a
            # canvas 2d context, neither of which is CSS.
            if '.style.' in line:
                continue
            if CANVAS.search(line):
                offenders.append(f'{p.relative_to(ROOT)}: {line.strip()[:70]}')
check(not offenders,
      f'no CSS variable assigned to a canvas or chart colour ({offenders[:2]})')


print('\n4. Every page using a token actually loads the stylesheet')
# A token that resolves to nothing is not a fallback -- `color: var(--ink)`
# with no definition leaves the text unstyled, and on a white card that can
# mean invisible.
offenders = []
for p in templates():
    text = p.read_text(errors='replace')
    if 'var(--' not in text:
        continue
    if parent_of(p) is None and '<html' not in text.lower():
        continue                           # an include, styled by its host
    if ':root' in text:
        continue                           # defines its own palette
    if not loads_design_system(p):
        offenders.append(str(p.relative_to(ROOT)))
check(not offenders, f'every page using tokens can resolve them ({offenders[:4]})')


print('\n5. The old palette is gone, and new literals are accounted for')
# A raw count was the wrong shape for this. Literals are not the problem --
# OUR palette being retyped by hand is. Some hex is legitimate and always will
# be: a meta tag the CSS engine never sees, the stops of a gradient, and above
# all a *customer's* own brand colour, which is theirs and cannot be one of our
# tokens by definition. So this names who is allowed how many, and why.
ALLOWED = {
    'admin/settings_business.html': (14, "the brand colour picker: a customer's "
                                         "own colours and the preview swatches"),
    'marketing/home.html':          (14, 'browser-chrome dots and gradient stops'),
    'marketing/_shell.html':        (10, 'the lit button gradient stops'),
    'admin/login_shell.html':        (2, 'theme-color meta tag'),
    'admin/login.html':              (2, 'theme-color meta tag'),
    'admin/signup.html':             (2, 'inherited shell'),
    'marketing/workspace.html':      (2, 'inherited shell'),
    'base_admin.html':               (2, 'theme-color meta tag'),
    'public/checklist.html':         (2, 'signature pad fallback'),
    'public/my_day.html':            (2, 'theme-color meta tag'),
    'public/book.html':              (2, "fallback for a business that has set no colour"),
    'interview/interview.html':      (2, 'its own :root aliases'),
}
OLD = {'#d3a84f', '#1f1333', '#9a95ad', '#5f5878', '#e4dfef', '#b98a33'}
unexplained, over, still_old = [], [], {}
for p in templates():
    if not loads_design_system(p):
        continue
    found = [h.lower() for h in re.findall(r'#[0-9a-fA-F]{6}\b',
                                           p.read_text(errors='replace'))]
    if not found:
        continue
    rel = str(p.relative_to(TEMPLATES))
    for h in found:
        if h in OLD:
            still_old[rel] = h
    if rel not in ALLOWED:
        unexplained.append(f'{rel} ({len(found)})')
    elif len(found) > ALLOWED[rel][0]:
        over.append(f'{rel}: {len(found)} > {ALLOWED[rel][0]} allowed')

check(not still_old, f'none of the six old signature colours remain ({still_old})')
check(not unexplained,
      f'no page grows hardcoded colours without a stated reason ({unexplained})')
check(not over, f'and no listed page drifts past its allowance ({over})')


print('\n6. The cleaner\'s phone pages are on the system')
# These are standalone pages -- they extend nothing -- so they are the ones
# most likely to be left behind by a sweep that walks the inheritance tree.
for name in ('my_day.html', 'checklist.html', 'claim.html'):
    p = TEMPLATES / 'public' / name
    check(p.exists() and loads_design_system(p),
          f'public/{name} loads the design system')


print('\n7. Every full page is on the system at all')
# Check 4 only catches a page that uses tokens without loading them. It said
# nothing about the sign-in screen, which used no tokens whatsoever -- it was
# still entirely the old gold and purple, and it is the first thing anybody
# sees. A page with its own <html> renders to somebody; it has to be on the
# palette or be listed here with a reason.
OFF_SYSTEM = {
    # nothing yet -- add a path here only with a reason it cannot use the
    # stylesheet, e.g. an email body, which no mail client will fetch CSS for
}
stragglers = []
for p in templates():
    text = p.read_text(errors='replace')
    if '<html' not in text.lower():
        continue                           # a fragment, styled by its host
    rel = str(p.relative_to(ROOT))
    if rel in OFF_SYSTEM:
        continue
    if not loads_design_system(p):
        stragglers.append(rel)
check(not stragglers,
      f'every page that renders to somebody loads the palette ({stragglers[:4]})')


print('\n8. Tap targets on the phone pages are thumb-sized')
# 48px is the accepted minimum for a finger. The cleaner is standing outside
# holding a phone in one hand, which is the whole reason this page exists.
day = (TEMPLATES / 'public' / 'my_day.html').read_text()
check('min-height:48px' in day.replace(' ', ''),
      "the day sheet's buttons are at least 48px tall")
check('Navigate' in day and 'btn-nav' in day,
      'and Navigate is styled as the primary action')


if failures:
    print(f'\n\n❌ {len(failures)} design check(s) failed.\n')
    sys.exit(1)
print('\n\n✅ The design system holds.\n')
