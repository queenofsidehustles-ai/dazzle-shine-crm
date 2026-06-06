import os
import requests as http_requests
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from auth import login_required
from models import ContentPost
from extensions import db

content_bp = Blueprint('content', __name__, url_prefix='/content')

_BIZ = "Dazzle & Shine Maids — professional home cleaning service in Orlando, FL."

_PROMPTS = {
    'before_after': 'Write an engaging caption for a before-and-after cleaning transformation post. Be vivid and celebratory.',
    'promo':        'Write a promotional post for a cleaning special or limited-time offer. Create urgency.',
    'tip':          'Write a helpful home cleaning tip that positions us as cleaning experts. Be practical and friendly.',
    'review':       'Write a social media post celebrating a glowing 5-star customer review. Be warm and grateful.',
    'seasonal':     'Write a seasonal cleaning post (spring cleaning, holiday prep, back-to-school, etc.). Be timely and relevant.',
    'hiring':       'Write a social media job post recruiting professional house cleaners. Be inviting and clear about benefits.',
}

_PLATFORM = {
    'instagram': 'Instagram — include 10-15 hashtags at the end. Keep it visual and engaging.',
    'facebook':  'Facebook — conversational, 2-3 short paragraphs, 3-5 hashtags max.',
    'tiktok':    'TikTok — write a punchy video hook (first line), then bullet-point on-screen text ideas for the video.',
    'google':    'Google Business Post — 150-300 characters, clear call to action, no hashtags.',
}


@content_bp.route('/')
@login_required
def index():
    posts = ContentPost.query.order_by(ContentPost.created_at.desc()).all()
    return render_template('admin/content.html', posts=posts,
                           post_types=list(_PROMPTS.keys()),
                           platforms=list(_PLATFORM.keys()))


@content_bp.route('/generate', methods=['POST'])
@login_required
def generate():
    post_type = request.form.get('post_type', 'tip')
    platform = request.form.get('platform', 'instagram')
    context = request.form.get('context', '').strip()

    api_key = os.environ.get('OPENROUTER_API_KEY')
    if not api_key:
        flash('Add OPENROUTER_API_KEY to Railway to enable AI content generation.', 'error')
        return redirect(url_for('content.index'))

    prompt = (
        f"Business: {_BIZ}\n\n"
        f"Task: {_PROMPTS.get(post_type, _PROMPTS['tip'])}\n"
        f"Platform: {_PLATFORM.get(platform, _PLATFORM['instagram'])}\n"
        + (f"Additional context: {context}\n" if context else '') +
        "\nWrite only the post content. No explanation or preamble."
    )

    try:
        res = http_requests.post(
            'https://openrouter.ai/api/v1/chat/completions',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={'model': 'anthropic/claude-haiku-4-5',
                  'messages': [{'role': 'user', 'content': prompt}], 'max_tokens': 500},
            timeout=30,
        )
        caption = res.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        flash(f'AI generation failed. Check your OpenRouter API key. ({e})', 'error')
        return redirect(url_for('content.index'))

    post = ContentPost(post_type=post_type, platform=platform,
                       caption=caption, context=context, status='draft')
    db.session.add(post)
    db.session.commit()
    flash('Content generated!', 'success')
    return redirect(url_for('content.index'))


@content_bp.route('/<int:post_id>/schedule', methods=['POST'])
@login_required
def schedule(post_id):
    post = ContentPost.query.get_or_404(post_id)
    post.scheduled_date = request.form.get('scheduled_date', '')
    post.status = 'scheduled'
    db.session.commit()
    flash('Post scheduled!', 'success')
    return redirect(url_for('content.index'))


@content_bp.route('/<int:post_id>/mark-posted', methods=['POST'])
@login_required
def mark_posted(post_id):
    post = ContentPost.query.get_or_404(post_id)
    post.status = 'posted'
    db.session.commit()
    return jsonify({'ok': True})


@content_bp.route('/<int:post_id>/delete', methods=['POST'])
@login_required
def delete(post_id):
    post = ContentPost.query.get_or_404(post_id)
    db.session.delete(post)
    db.session.commit()
    flash('Post deleted.', 'success')
    return redirect(url_for('content.index'))
