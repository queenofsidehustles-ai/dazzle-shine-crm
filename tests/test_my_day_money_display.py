"""PAY-01: My Day must preserve exact cents for cleaner earnings."""
from pathlib import Path


def test_my_day_template_preserves_exact_cents():
    template = (Path(__file__).resolve().parents[1] / 'templates' / 'public' / 'my_day.html').read_text()
    assert "'%.2f'|format(b.pay_for(s))" in template
    assert "'%.0f'|format(b.pay_for(s))" not in template
