from flask import Blueprint, render_template, request, redirect, url_for, flash
from entitlements import requires_plan
from auth import login_required
from models import SOP
from extensions import db
import branding

sops_bp = Blueprint('sops', __name__, url_prefix='/sops')


@sops_bp.route('/')
@login_required
@requires_plan('sops')
def index():
    category = request.args.get('cat', 'cleaning')
    sops = SOP.query.filter_by(category=category).order_by(SOP.sort_order, SOP.id).all()
    counts = {c: SOP.query.filter_by(category=c).count() for c, _ in SOP.CATEGORIES}
    return render_template('admin/sops.html',
                           sops=sops, active_cat=category,
                           categories=SOP.CATEGORIES, counts=counts)


# Categories cleaners should see (not admin/lead-handling ones)
CLEANER_CATEGORIES = ['cleaning', 'commercial', 'quality']


@sops_bp.route('/library')
def library():
    """Public SOP library cleaners can reference anytime (job-relevant categories only)."""
    from models import BusinessSetting
    biz = branding.biz_name()
    label_map = dict(SOP.CATEGORIES)
    groups = []
    for key in CLEANER_CATEGORIES:
        items = SOP.query.filter_by(category=key).order_by(SOP.sort_order, SOP.id).all()
        if items:
            groups.append({'label': label_map.get(key, key), 'items': items})
    return render_template('public/sop_library.html', biz=biz, groups=groups)


@sops_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    if request.method == 'POST':
        s = SOP(
            category=request.form.get('category', 'cleaning'),
            title=request.form.get('title', '').strip(),
            content=request.form.get('content', '').strip(),
            sort_order=int(request.form.get('sort_order', 0)),
        )
        db.session.add(s)
        db.session.commit()
        flash('SOP added!', 'success')
        return redirect(url_for('sops.index', cat=s.category))
    category = request.args.get('cat', 'cleaning')
    return render_template('admin/sop_form.html',
                           sop=None, category=category,
                           categories=SOP.CATEGORIES)


@sops_bp.route('/<int:sop_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(sop_id):
    s = SOP.query.get_or_404(sop_id)
    if request.method == 'POST':
        s.category = request.form.get('category', s.category)
        s.title = request.form.get('title', s.title).strip()
        s.content = request.form.get('content', s.content).strip()
        s.sort_order = int(request.form.get('sort_order', s.sort_order))
        db.session.commit()
        flash('SOP updated!', 'success')
        return redirect(url_for('sops.index', cat=s.category))
    return render_template('admin/sop_form.html',
                           sop=s, category=s.category,
                           categories=SOP.CATEGORIES)


@sops_bp.route('/<int:sop_id>/delete', methods=['POST'])
@login_required
def delete(sop_id):
    s = SOP.query.get_or_404(sop_id)
    cat = s.category
    db.session.delete(s)
    db.session.commit()
    flash('SOP deleted.', 'success')
    return redirect(url_for('sops.index', cat=cat))
