from flask import Blueprint, render_template, request, redirect, url_for, flash
from auth import login_required
from models import SOP
from extensions import db

sops_bp = Blueprint('sops', __name__, url_prefix='/sops')


@sops_bp.route('/')
@login_required
def index():
    category = request.args.get('cat', 'cleaning')
    sops = SOP.query.filter_by(category=category).order_by(SOP.sort_order, SOP.id).all()
    counts = {c: SOP.query.filter_by(category=c).count() for c, _ in SOP.CATEGORIES}
    return render_template('admin/sops.html',
                           sops=sops, active_cat=category,
                           categories=SOP.CATEGORIES, counts=counts)


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
