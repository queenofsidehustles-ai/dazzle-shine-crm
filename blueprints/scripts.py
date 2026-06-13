from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from auth import login_required
from models import Script
from extensions import db

scripts_bp = Blueprint('scripts', __name__, url_prefix='/scripts')


@scripts_bp.route('/')
@login_required
def index():
    category = request.args.get('cat', 'inbound')
    scripts = Script.query.filter_by(category=category).order_by(Script.sort_order, Script.id).all()
    counts = {c: Script.query.filter_by(category=c).count() for c, _ in Script.CATEGORIES}
    return render_template('admin/scripts.html',
                           scripts=scripts, active_cat=category,
                           categories=Script.CATEGORIES, counts=counts)


@scripts_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    if request.method == 'POST':
        s = Script(
            category=request.form.get('category', 'general'),
            title=request.form.get('title', '').strip(),
            content=request.form.get('content', '').strip(),
            sort_order=int(request.form.get('sort_order', 0)),
        )
        db.session.add(s)
        db.session.commit()
        flash('Script added!', 'success')
        return redirect(url_for('scripts.index', cat=s.category))
    category = request.args.get('cat', 'general')
    return render_template('admin/script_form.html',
                           script=None, category=category,
                           categories=Script.CATEGORIES)


@scripts_bp.route('/<int:script_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(script_id):
    s = Script.query.get_or_404(script_id)
    if request.method == 'POST':
        s.category = request.form.get('category', s.category)
        s.title = request.form.get('title', s.title).strip()
        s.content = request.form.get('content', s.content).strip()
        s.sort_order = int(request.form.get('sort_order', s.sort_order))
        db.session.commit()
        flash('Script updated!', 'success')
        return redirect(url_for('scripts.index', cat=s.category))
    return render_template('admin/script_form.html',
                           script=s, category=s.category,
                           categories=Script.CATEGORIES)


@scripts_bp.route('/<int:script_id>/delete', methods=['POST'])
@login_required
def delete(script_id):
    s = Script.query.get_or_404(script_id)
    cat = s.category
    db.session.delete(s)
    db.session.commit()
    flash('Script deleted.', 'success')
    return redirect(url_for('scripts.index', cat=cat))
