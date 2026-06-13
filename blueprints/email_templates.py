from flask import Blueprint, render_template, request, redirect, url_for, flash
from auth import login_required
from models import EmailTemplate
from extensions import db

email_templates_bp = Blueprint('email_templates', __name__, url_prefix='/email-templates')


@email_templates_bp.route('/')
@login_required
def index():
    category = request.args.get('cat', 'client')
    templates = EmailTemplate.query.filter_by(category=category).order_by(EmailTemplate.id).all()
    counts = {c: EmailTemplate.query.filter_by(category=c).count() for c, _ in EmailTemplate.CATEGORIES}
    variables = EmailTemplate.VARIABLES.get(category, [])
    return render_template('admin/email_templates.html',
                           templates=templates, active_cat=category,
                           categories=EmailTemplate.CATEGORIES,
                           counts=counts, variables=variables)


@email_templates_bp.route('/<int:tmpl_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(tmpl_id):
    t = EmailTemplate.query.get_or_404(tmpl_id)
    if request.method == 'POST':
        t.subject = request.form.get('subject', t.subject).strip()
        t.body = request.form.get('body', t.body).strip()
        t.is_active = 'is_active' in request.form
        db.session.commit()
        flash('Email template saved!', 'success')
        return redirect(url_for('email_templates.index', cat=t.category))
    variables = EmailTemplate.VARIABLES.get(t.category, [])
    return render_template('admin/email_template_edit.html',
                           t=t, variables=variables,
                           categories=EmailTemplate.CATEGORIES)


@email_templates_bp.route('/<int:tmpl_id>/toggle', methods=['POST'])
@login_required
def toggle(tmpl_id):
    t = EmailTemplate.query.get_or_404(tmpl_id)
    t.is_active = not t.is_active
    db.session.commit()
    status = 'enabled' if t.is_active else 'paused'
    flash(f'"{t.name}" {status}.', 'success')
    return redirect(url_for('email_templates.index', cat=t.category))
