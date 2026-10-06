from flask import Blueprint, render_template, request, redirect, url_for, flash
from auth import login_required
from models import Faq
from extensions import db

faq_bp = Blueprint('faq', __name__, url_prefix='/faq')


@faq_bp.route('/')
@login_required
def index():
    """Every FAQ, or the ones matching a search word.

    Matched against both the question and the answer -- somebody
    searching for a word they remember from the fix, not just the
    question, should still find it.
    """
    q = (request.args.get('q') or '').strip()
    query = Faq.query
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(Faq.question.ilike(like), Faq.answer.ilike(like)))
    faqs = query.order_by(Faq.question).all()
    return render_template('admin/faqs.html', faqs=faqs, q=q, total=Faq.query.count())


@faq_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    if request.method == 'POST':
        question = (request.form.get('question') or '').strip()
        answer = (request.form.get('answer') or '').strip()
        if not question or not answer:
            flash('Both the question and the answer are needed.', 'error')
            return render_template('admin/faq_form.html', faq=None,
                                   question=question, answer=answer)
        f = Faq(question=question, answer=answer)
        db.session.add(f)
        db.session.commit()
        flash('Added to the Knowledge Base.', 'success')
        return redirect(url_for('faq.index'))
    return render_template('admin/faq_form.html', faq=None, question='', answer='')


@faq_bp.route('/<int:faq_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(faq_id):
    f = Faq.query.get_or_404(faq_id)
    if request.method == 'POST':
        question = (request.form.get('question') or '').strip()
        answer = (request.form.get('answer') or '').strip()
        if not question or not answer:
            flash('Both the question and the answer are needed.', 'error')
            return render_template('admin/faq_form.html', faq=f,
                                   question=question, answer=answer)
        f.question = question
        f.answer = answer
        db.session.commit()
        flash('Updated.', 'success')
        return redirect(url_for('faq.index'))
    return render_template('admin/faq_form.html', faq=f, question=f.question, answer=f.answer)


@faq_bp.route('/<int:faq_id>/delete', methods=['POST'])
@login_required
def delete(faq_id):
    f = Faq.query.get_or_404(faq_id)
    db.session.delete(f)
    db.session.commit()
    flash('Removed.', 'success')
    return redirect(url_for('faq.index'))
