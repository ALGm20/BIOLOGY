"""
UniPortal - قسم علوم الحياة
Flask backend - Production ready
"""
import os, json, base64
from datetime import datetime, timedelta
from functools import wraps
from flask import (Flask, render_template, request, jsonify,
                   session, redirect, url_for, send_from_directory)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# ── Try pywebpush for push notifications ──
try:
    from pywebpush import webpush, WebPushException
    PUSH_OK = True
except ImportError:
    PUSH_OK = False

# ═══════════════════════════════════════════
#  APP CONFIG
# ═══════════════════════════════════════════
app = Flask(__name__)
app.config.update(
    SECRET_KEY          = os.environ.get('SECRET_KEY', 'uniportal-secret-2025-change-in-prod'),
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:////tmp/uniportal.db').replace('postgres://', 'postgresql://'),
    SQLALCHEMY_TRACK_MODIFICATIONS = False,
    UPLOAD_FOLDER       = os.environ.get('UPLOAD_FOLDER', '/tmp/uploads'),
    MAX_CONTENT_LENGTH  = 50 * 1024 * 1024,   # 50 MB
    VAPID_PUBLIC_KEY    = os.environ.get('VAPID_PUBLIC_KEY',
        'BBOhs6s7-f4lYor-KTFU9nPBwxlgWgxzq-xQnVEtgFJv2Mq8O_G-0fyVdhzEbtlI4rbi4jBwHSLg5uyglQwds60'),
    VAPID_PRIVATE_KEY   = os.environ.get('VAPID_PRIVATE_KEY', 
                          open(os.path.join(os.path.dirname(__file__), 'vapid_private.pem')).read()
                          if os.path.exists(os.path.join(os.path.dirname(__file__), 'vapid_private.pem')) else ''),
    VAPID_CLAIMS        = {'sub': 'mailto:admin@uniportal.edu'},
)

ALLOWED_EXT = {'pdf','png','jpg','jpeg','gif','webp','doc','docx','ppt','pptx','xls','xlsx','mp4','mp3'}
db = SQLAlchemy(app)

# ═══════════════════════════════════════════
#  ROLE PERMISSIONS
# ═══════════════════════════════════════════
ROLES = {
    'رئيس':  {'level': 5, 'see_private': False, 'post_gen': False, 'create_ch': False, 'is_admin': True},
    'مقرر':  {'level': 4, 'see_private': False, 'post_gen': True,  'create_ch': False, 'is_admin': True},
    'دكتور': {'level': 3, 'see_private': True,  'post_gen': False, 'create_ch': True,  'is_admin': False},
    'ممثل':  {'level': 2, 'see_private': True,  'post_gen': False, 'create_ch': True,  'is_admin': False},
    'طالب':  {'level': 1, 'see_private': True,  'post_gen': False, 'create_ch': False, 'is_admin': False},
}

# ═══════════════════════════════════════════
#  MODELS
# ═══════════════════════════════════════════
class Section(db.Model):
    id   = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False)

class User(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    uid           = db.Column(db.String(30), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    name_ar       = db.Column(db.String(120), nullable=False)
    name_en       = db.Column(db.String(120))
    role          = db.Column(db.String(20), nullable=False, default='طالب')
    section_id    = db.Column(db.Integer, db.ForeignKey('section.id'), nullable=True)
    bio           = db.Column(db.String(200))
    photo_url     = db.Column(db.String(300))
    online        = db.Column(db.Boolean, default=False)
    active        = db.Column(db.Boolean, default=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    section       = db.relationship('Section', backref='members')

    def get_role(self): return ROLES.get(self.role, ROLES['طالب'])
    def can_post_gen(self): return self.get_role()['post_gen']
    def can_create_ch(self): return self.get_role()['create_ch']
    def is_admin(self): return self.get_role()['is_admin']
    def see_private(self): return self.get_role()['see_private']

    def to_dict(self):
        return {
            'id': self.id, 'uid': self.uid,
            'name_ar': self.name_ar, 'name_en': self.name_en,
            'role': self.role, 'section_id': self.section_id,
            'bio': self.bio, 'photo_url': self.photo_url,
            'online': self.online, 'active': self.active,
            'section_name': self.section.name if self.section else None,
        }

class Channel(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    ch_key      = db.Column(db.String(60), unique=True, nullable=False)
    name_ar     = db.Column(db.String(120), nullable=False)
    name_en     = db.Column(db.String(120))
    desc_ar     = db.Column(db.String(300))
    desc_en     = db.Column(db.String(300))
    ch_type     = db.Column(db.String(20), nullable=False)  # ann|doc|rep
    owner_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    section_id  = db.Column(db.Integer, db.ForeignKey('section.id'), nullable=True)
    photo_url   = db.Column(db.String(300))
    icon        = db.Column(db.String(10), default='💬')
    color       = db.Column(db.String(10), default='#00d4ff')
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    owner       = db.relationship('User', backref='owned_channels')
    section     = db.relationship('Section', backref='channels')

    def to_dict(self):
        return {
            'id': self.id, 'ch_key': self.ch_key,
            'name_ar': self.name_ar, 'name_en': self.name_en,
            'desc_ar': self.desc_ar, 'desc_en': self.desc_en,
            'ch_type': self.ch_type,
            'owner_id': self.owner_id,
            'owner_name': self.owner.name_ar if self.owner else None,
            'section_id': self.section_id,
            'section_name': self.section.name if self.section else None,
            'photo_url': self.photo_url,
            'icon': self.icon, 'color': self.color,
        }

class Message(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    channel_id  = db.Column(db.Integer, db.ForeignKey('channel.id'), nullable=False)
    sender_id   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    msg_type    = db.Column(db.String(20), default='txt')  # txt|pdf|img|lnk|sys
    text        = db.Column(db.Text)
    file_path   = db.Column(db.String(400))
    file_name   = db.Column(db.String(200))
    link_url    = db.Column(db.String(500))
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    channel     = db.relationship('Channel', backref=db.backref('messages', lazy='dynamic', order_by='Message.created_at'))
    sender      = db.relationship('User', backref='messages')

    def to_dict(self):
        return {
            'id': self.id,
            'channel_id': self.channel_id,
            'channel_key': self.channel.ch_key,
            'sender_id': self.sender_id,
            'sender_name': self.sender.name_ar if self.sender else None,
            'sender_role': self.sender.role if self.sender else None,
            'msg_type': self.msg_type,
            'text': self.text,
            'file_path': self.file_path,
            'file_name': self.file_name,
            'link_url': self.link_url,
            'created_at': self.created_at.strftime('%Y-%m-%dT%H:%M:%S'),
        }

class Announcement(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    author_id   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title_ar    = db.Column(db.String(200), nullable=False)
    title_en    = db.Column(db.String(200))
    content_ar  = db.Column(db.Text)
    content_en  = db.Column(db.Text)
    file_path   = db.Column(db.String(400))
    file_name   = db.Column(db.String(200))
    link_url    = db.Column(db.String(500))
    link_label  = db.Column(db.String(100))
    pinned      = db.Column(db.Boolean, default=False)
    views       = db.Column(db.Integer, default=0)
    emoji       = db.Column(db.String(10), default='📢')
    color       = db.Column(db.String(10), default='#0066cc')
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    author      = db.relationship('User', backref='announcements')

    def to_dict(self):
        return {
            'id': self.id,
            'author_id': self.author_id,
            'author_name': self.author.name_ar if self.author else None,
            'title_ar': self.title_ar, 'title_en': self.title_en,
            'content_ar': self.content_ar, 'content_en': self.content_en,
            'file_path': self.file_path, 'file_name': self.file_name,
            'link_url': self.link_url, 'link_label': self.link_label,
            'pinned': self.pinned, 'views': self.views,
            'emoji': self.emoji, 'color': self.color,
            'created_at': self.created_at.strftime('%Y-%m-%dT%H:%M:%S'),
        }

class PushSub(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    user_id   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sub_json  = db.Column(db.Text, nullable=False)
    created_at= db.Column(db.DateTime, default=datetime.utcnow)

class Notification(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title_ar   = db.Column(db.String(200))
    title_en   = db.Column(db.String(200))
    body_ar    = db.Column(db.String(400))
    body_en    = db.Column(db.String(400))
    ch_key     = db.Column(db.String(60))
    is_read    = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'title_ar': self.title_ar, 'title_en': self.title_en,
            'body_ar': self.body_ar, 'body_en': self.body_en,
            'ch_key': self.ch_key, 'is_read': self.is_read,
            'created_at': self.created_at.strftime('%Y-%m-%dT%H:%M:%S'),
        }

# ═══════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════
def login_required(f):
    @wraps(f)
    def decorated(*a, **kw):
        if 'user_id' not in session:
            return jsonify({'ok': False, 'error': 'unauthorized'}), 401
        return f(*a, **kw)
    return decorated

def current_user():
    uid = session.get('user_id')
    return User.query.get(uid) if uid else None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT

def visible_channels(user):
    """Return list of channels this user can see."""
    all_chs = Channel.query.all()
    result = []
    rd = ROLES.get(user.role, ROLES['طالب'])
    for ch in all_chs:
        if ch.ch_type == 'ann':
            result.append(ch)
            continue
        if not rd['see_private']:
            continue
        if ch.ch_type in ('doc', 'rep'):
            if ch.owner_id == user.id or ch.section_id == user.section_id:
                result.append(ch)
    return result

def can_write_channel(user, channel):
    if channel.ch_type == 'ann':
        return user.can_post_gen()
    if channel.ch_type in ('doc', 'rep'):
        return channel.owner_id == user.id
    return False

def send_push(user_id, title, body, url='/'):
    if not PUSH_OK: return
    subs = PushSub.query.filter_by(user_id=user_id).all()
    payload = json.dumps({'title': title, 'body': body, 'url': url})
    dead = []
    for sub in subs:
        try:
            webpush(
                subscription_info=json.loads(sub.sub_json),
                data=payload,
                vapid_private_key=app.config['VAPID_PRIVATE_KEY'],
                vapid_claims=app.config['VAPID_CLAIMS']
            )
        except Exception:
            dead.append(sub.id)
    if dead:
        PushSub.query.filter(PushSub.id.in_(dead)).delete()
        db.session.commit()

def notify_channel_members(channel, title_ar, title_en, body_ar, body_en):
    """Create DB notifications and send push to all channel members."""
    if channel.ch_type == 'ann':
        users = User.query.filter_by(active=True).all()
    else:
        users = User.query.filter(
            (User.id == channel.owner_id) | (User.section_id == channel.section_id)
        ).filter_by(active=True).all()

    for u in users:
        n = Notification(
            user_id=u.id, title_ar=title_ar, title_en=title_en,
            body_ar=body_ar, body_en=body_en, ch_key=channel.ch_key
        )
        db.session.add(n)
        send_push(u.id, title_ar, body_ar)
    db.session.commit()

# ═══════════════════════════════════════════
#  ROUTES - AUTH
# ═══════════════════════════════════════════
@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json() or {}
    uid  = data.get('uid', '').strip().upper()
    pwd  = data.get('password', '')
    user = User.query.filter_by(uid=uid, active=True).first()
    if not user:
        return jsonify({'ok': False, 'error': 'الرقم الجامعي غير موجود'})
    if not check_password_hash(user.password_hash, pwd):
        return jsonify({'ok': False, 'error': 'كلمة المرور غير صحيحة'})
    session['user_id'] = user.id
    user.online = True
    db.session.commit()
    return jsonify({'ok': True, 'user': user.to_dict()})

@app.route('/api/logout', methods=['POST'])
def api_logout():
    u = current_user()
    if u:
        u.online = False
        db.session.commit()
    session.clear()
    return jsonify({'ok': True})

@app.route('/api/me')
@login_required
def api_me():
    return jsonify(current_user().to_dict())

@app.route('/api/me', methods=['PATCH'])
@login_required
def api_update_me():
    u = current_user()
    data = request.get_json() or {}
    if 'name_ar' in data: u.name_ar = data['name_ar'][:120]
    if 'name_en' in data: u.name_en = data['name_en'][:120]
    if 'bio'     in data: u.bio     = data['bio'][:200]
    if 'password' in data and data['password']:
        u.password_hash = generate_password_hash(data['password'])
    db.session.commit()
    return jsonify({'ok': True, 'user': u.to_dict()})

# ═══════════════════════════════════════════
#  ROUTES - USERS (admin)
# ═══════════════════════════════════════════
@app.route('/api/users')
@login_required
def api_users():
    u = current_user()
    if not u.is_admin():
        return jsonify({'error': 'forbidden'}), 403
    page  = request.args.get('page', 1, type=int)
    query = request.args.get('q', '')
    q = User.query
    if query:
        q = q.filter(User.name_ar.ilike(f'%{query}%') | User.uid.ilike(f'%{query}%'))
    users = q.paginate(page=page, per_page=30)
    return jsonify({
        'users': [u.to_dict() for u in users.items],
        'total': users.total, 'pages': users.pages,
    })

@app.route('/api/users/<int:uid>', methods=['PATCH'])
@login_required
def api_update_user(uid):
    me = current_user()
    if not me.is_admin(): return jsonify({'error': 'forbidden'}), 403
    target = User.query.get_or_404(uid)
    data   = request.get_json() or {}
    if 'role' in data and data['role'] in ROLES:
        if data['role'] == 'رئيس' and me.role != 'رئيس':
            return jsonify({'error': 'Insufficient permissions'}), 403
        target.role = data['role']
    if 'section_id' in data: target.section_id = data['section_id'] or None
    if 'active'     in data: target.active      = bool(data['active'])
    db.session.commit()
    return jsonify({'ok': True})

# ═══════════════════════════════════════════
#  ROUTES - SECTIONS
# ═══════════════════════════════════════════
@app.route('/api/sections')
def api_sections():
    return jsonify([{'id': s.id, 'name': s.name} for s in Section.query.all()])

@app.route('/api/sections', methods=['POST'])
@login_required
def api_create_section():
    u = current_user()
    if not u.is_admin(): return jsonify({'error': 'forbidden'}), 403
    data = request.get_json() or {}
    s = Section(name=data.get('name', 'شعبة جديدة'))
    db.session.add(s)
    db.session.commit()
    return jsonify({'ok': True, 'id': s.id})

# ═══════════════════════════════════════════
#  ROUTES - CHANNELS
# ═══════════════════════════════════════════
@app.route('/api/channels')
@login_required
def api_channels():
    u = current_user()
    chs = visible_channels(u)
    # attach unread count
    result = []
    for ch in chs:
        d = ch.to_dict()
        # last message
        last = ch.messages.order_by(Message.created_at.desc()).first()
        if last:
            d['last_msg']  = last.text[:60] if last.text else ({'pdf':'📄 ملف','img':'🖼️ صورة','lnk':'🔗 رابط'}.get(last.msg_type,''))
            d['last_time'] = last.created_at.strftime('%Y-%m-%dT%H:%M:%S')
        else:
            d['last_msg'] = ''; d['last_time'] = None
        d['unread'] = 0  # simplified
        d['can_write'] = can_write_channel(u, ch)
        result.append(d)
    return jsonify(result)

@app.route('/api/channels', methods=['POST'])
@login_required
def api_create_channel():
    u = current_user()
    if not u.can_create_ch(): return jsonify({'error': 'forbidden'}), 403
    data = request.get_json() or {}
    ch_type = 'doc' if u.role == 'دكتور' else 'rep'
    import time
    ch = Channel(
        ch_key    = f'ch_{u.id}_{int(time.time())}',
        name_ar   = data.get('name_ar', 'قناة جديدة')[:120],
        name_en   = data.get('name_en', 'New Channel')[:120],
        desc_ar   = data.get('desc_ar', '')[:300],
        desc_en   = data.get('desc_en', '')[:300],
        ch_type   = ch_type,
        owner_id  = u.id,
        section_id= u.section_id,
        icon      = '🔬' if ch_type == 'doc' else '📣',
        color     = '#00d4ff' if ch_type == 'doc' else '#a855f7',
    )
    db.session.add(ch)
    db.session.flush()
    # sys message
    msg = Message(
        channel_id=ch.id, msg_type='sys',
        text=f'تم إنشاء القناة بواسطة {u.name_ar}'
    )
    db.session.add(msg)
    db.session.commit()
    return jsonify({'ok': True, 'channel': ch.to_dict()})

@app.route('/api/channels/<string:ch_key>')
@login_required
def api_channel_detail(ch_key):
    u  = current_user()
    ch = Channel.query.filter_by(ch_key=ch_key).first_or_404()
    if ch not in visible_channels(u): return jsonify({'error': 'forbidden'}), 403
    d = ch.to_dict()
    d['can_write'] = can_write_channel(u, ch)
    return jsonify(d)

# ═══════════════════════════════════════════
#  ROUTES - MESSAGES
# ═══════════════════════════════════════════
@app.route('/api/channels/<string:ch_key>/messages')
@login_required
def api_messages(ch_key):
    u  = current_user()
    ch = Channel.query.filter_by(ch_key=ch_key).first_or_404()
    if ch not in visible_channels(u): return jsonify({'error': 'forbidden'}), 403
    page = request.args.get('page', 1, type=int)
    msgs = ch.messages.order_by(Message.created_at.desc()).paginate(page=page, per_page=50)
    return jsonify({
        'messages': [m.to_dict() for m in reversed(msgs.items)],
        'has_more': msgs.has_next,
    })

@app.route('/api/channels/<string:ch_key>/messages', methods=['POST'])
@login_required
def api_send_message(ch_key):
    u  = current_user()
    ch = Channel.query.filter_by(ch_key=ch_key).first_or_404()
    if not can_write_channel(u, ch): return jsonify({'error': 'forbidden'}), 403

    text     = request.form.get('text', '').strip()
    link_url = request.form.get('link_url', '').strip()
    file     = request.files.get('file')
    msg_type = 'txt'
    file_path = None
    file_name = None

    if file and file.filename and allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        fn  = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secure_filename(file.filename)}"
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        fp  = os.path.join(app.config['UPLOAD_FOLDER'], fn)
        file.save(fp)
        file_path = f'/uploads/{fn}'
        file_name = file.filename
        msg_type  = 'pdf' if ext == 'pdf' else ('img' if ext in ('png','jpg','jpeg','gif','webp') else 'file')
    elif link_url:
        msg_type = 'lnk'
    elif not text:
        return jsonify({'error': 'empty message'}), 400

    msg = Message(
        channel_id=ch.id, sender_id=u.id,
        msg_type=msg_type, text=text or None,
        file_path=file_path, file_name=file_name,
        link_url=link_url or None,
    )
    db.session.add(msg)
    db.session.commit()

    # Notify
    preview = text[:60] if text else (file_name or link_url or '')
    notify_channel_members(
        ch,
        title_ar=f'رسالة في {ch.name_ar}',
        title_en=f'Message in {ch.name_en or ch.name_ar}',
        body_ar=f'{u.name_ar}: {preview}',
        body_en=f'{u.name_en or u.name_ar}: {preview}',
    )
    return jsonify({'ok': True, 'message': msg.to_dict()})

# ═══════════════════════════════════════════
#  ROUTES - ANNOUNCEMENTS
# ═══════════════════════════════════════════
@app.route('/api/announcements')
@login_required
def api_announcements():
    anns = Announcement.query.order_by(
        Announcement.pinned.desc(),
        Announcement.created_at.desc()
    ).all()
    return jsonify([a.to_dict() for a in anns])

@app.route('/api/announcements', methods=['POST'])
@login_required
def api_post_announcement():
    u = current_user()
    if not u.can_post_gen(): return jsonify({'error': 'forbidden'}), 403

    title_ar  = request.form.get('title_ar', '').strip()
    content_ar= request.form.get('content_ar', '').strip()
    title_en  = request.form.get('title_en', '').strip()
    content_en= request.form.get('content_en', '').strip()
    link_url  = request.form.get('link_url', '').strip()
    link_label= request.form.get('link_label', '').strip()
    pinned    = request.form.get('pinned', '0') == '1'
    emoji     = request.form.get('emoji', '📢')
    color     = request.form.get('color', '#0066cc')
    file      = request.files.get('file')

    file_path = None; file_name = None
    if file and file.filename and allowed_file(file.filename):
        fn = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secure_filename(file.filename)}"
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], fn))
        file_path = f'/uploads/{fn}'
        file_name = file.filename

    ann = Announcement(
        author_id=u.id, title_ar=title_ar, title_en=title_en or title_ar,
        content_ar=content_ar, content_en=content_en or content_ar,
        file_path=file_path, file_name=file_name,
        link_url=link_url or None, link_label=link_label or None,
        pinned=pinned, emoji=emoji, color=color,
    )
    db.session.add(ann)
    db.session.commit()

    # Push to all
    all_users = User.query.filter_by(active=True).all()
    for usr in all_users:
        n = Notification(
            user_id=usr.id, title_ar=title_ar, title_en=title_en or title_ar,
            body_ar=content_ar[:80], body_en=(content_en or content_ar)[:80],
        )
        db.session.add(n)
        send_push(usr.id, title_ar, content_ar[:80])
    db.session.commit()
    return jsonify({'ok': True, 'announcement': ann.to_dict()})

@app.route('/api/announcements/<int:ann_id>', methods=['DELETE'])
@login_required
def api_delete_ann(ann_id):
    u = current_user()
    ann = Announcement.query.get_or_404(ann_id)
    if ann.author_id != u.id and not u.is_admin():
        return jsonify({'error': 'forbidden'}), 403
    db.session.delete(ann)
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/announcements/<int:ann_id>/pin', methods=['POST'])
@login_required
def api_pin_ann(ann_id):
    u = current_user()
    if not u.can_post_gen() and not u.is_admin():
        return jsonify({'error': 'forbidden'}), 403
    ann = Announcement.query.get_or_404(ann_id)
    ann.pinned = not ann.pinned
    db.session.commit()
    return jsonify({'ok': True, 'pinned': ann.pinned})

@app.route('/api/announcements/<int:ann_id>/view', methods=['POST'])
@login_required
def api_view_ann(ann_id):
    ann = Announcement.query.get_or_404(ann_id)
    ann.views += 1
    db.session.commit()
    return jsonify({'ok': True})

# ═══════════════════════════════════════════
#  ROUTES - NOTIFICATIONS
# ═══════════════════════════════════════════
@app.route('/api/notifications')
@login_required
def api_notifications():
    u = current_user()
    notifs = Notification.query.filter_by(user_id=u.id)\
        .order_by(Notification.created_at.desc()).limit(50).all()
    return jsonify({
        'notifications': [n.to_dict() for n in notifs],
        'unread': Notification.query.filter_by(user_id=u.id, is_read=False).count(),
    })

@app.route('/api/notifications/read_all', methods=['POST'])
@login_required
def api_notifs_read_all():
    u = current_user()
    Notification.query.filter_by(user_id=u.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/notifications/<int:nid>/read', methods=['POST'])
@login_required
def api_notif_read(nid):
    u = current_user()
    n = Notification.query.filter_by(id=nid, user_id=u.id).first_or_404()
    n.is_read = True
    db.session.commit()
    return jsonify({'ok': True})

# ═══════════════════════════════════════════
#  ROUTES - PUSH
# ═══════════════════════════════════════════
@app.route('/api/push/subscribe', methods=['POST'])
@login_required
def api_push_subscribe():
    u    = current_user()
    data = request.get_json() or {}
    sub_json = json.dumps(data)
    existing = PushSub.query.filter_by(user_id=u.id).first()
    if existing:
        existing.sub_json = sub_json
    else:
        db.session.add(PushSub(user_id=u.id, sub_json=sub_json))
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/push/vapid-key')
def api_vapid_key():
    return jsonify({'key': app.config['VAPID_PUBLIC_KEY']})

# ═══════════════════════════════════════════
#  ROUTES - UPLOAD
# ═══════════════════════════════════════════
@app.route('/api/upload-photo', methods=['POST'])
@login_required
def api_upload_photo():
    u    = current_user()
    file = request.files.get('photo')
    if not file or not allowed_file(file.filename):
        return jsonify({'error': 'invalid file'}), 400
    fn = f"photo_{u.id}_{int(datetime.now().timestamp())}.{file.filename.rsplit('.',1)[1]}"
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], fn))
    u.photo_url = f'/uploads/{fn}'
    db.session.commit()
    return jsonify({'ok': True, 'url': u.photo_url})

@app.route('/api/upload-channel-photo', methods=['POST'])
@login_required
def api_upload_ch_photo():
    u    = current_user()
    ch_key = request.form.get('ch_key')
    ch = Channel.query.filter_by(ch_key=ch_key).first_or_404()
    if ch.owner_id != u.id and not u.is_admin():
        return jsonify({'error': 'forbidden'}), 403
    file = request.files.get('photo')
    if not file or not allowed_file(file.filename):
        return jsonify({'error': 'invalid file'}), 400
    fn = f"ch_{ch.id}_{int(datetime.now().timestamp())}.{file.filename.rsplit('.',1)[1]}"
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], fn))
    ch.photo_url = f'/uploads/{fn}'
    db.session.commit()
    return jsonify({'ok': True, 'url': ch.photo_url})

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ═══════════════════════════════════════════
#  ROUTES - STATS
# ═══════════════════════════════════════════
@app.route('/api/stats')
@login_required
def api_stats():
    u = current_user()
    if not u.is_admin(): return jsonify({'error': 'forbidden'}), 403
    from sqlalchemy import func
    by_role = db.session.query(User.role, func.count(User.id))\
        .filter_by(active=True).group_by(User.role).all()
    by_sec  = db.session.query(Section.name, func.count(User.id))\
        .join(User, User.section_id == Section.id)\
        .filter(User.role == 'طالب', User.active == True)\
        .group_by(Section.name).all()
    return jsonify({
        'total_users':    User.query.filter_by(active=True).count(),
        'online_users':   User.query.filter_by(online=True, active=True).count(),
        'total_channels': Channel.query.count(),
        'total_messages': Message.query.count(),
        'total_anns':     Announcement.query.count(),
        'by_role':        [{'role': r, 'count': c} for r, c in by_role],
        'by_section':     [{'name': n, 'count': c} for n, c in by_sec],
    })

# ═══════════════════════════════════════════
#  STATIC FILES & SPA
# ═══════════════════════════════════════════

@app.route('/health')
def health():
    return {'status': 'ok'}, 200

@app.route('/sw.js')
def sw():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def index(path):
    return send_from_directory('static', 'index.html')

# ═══════════════════════════════════════════
#  DB SEED
# ═══════════════════════════════════════════
def seed_db():
    db.create_all()
    if Section.query.first(): return  # already seeded

    # Sections
    secs = {}
    for name in ['Section A', 'Section B', 'Section C', 'Section D']:
        s = Section(name=name); db.session.add(s); db.session.flush(); secs[name] = s.id

    # Users
    default_pwd = generate_password_hash('1234')
    users = [
        dict(uid='HEAD001',   name_ar='أ.د. كريم الجبوري',  name_en='Prof. Kareem Al-Jabbouri', role='رئيس',  sec=None,         bio='رئيس قسم علوم الحياة'),
        dict(uid='COORD001',  name_ar='د. منى الكاظمي',     name_en='Dr. Mona Al-Kadhimi',      role='مقرر',  sec=None,         bio='مقررة قسم علوم الحياة'),
        dict(uid='DOC001',    name_ar='د. علي الحسيني',     name_en='Dr. Ali Al-Husseini',      role='دكتور', sec='Section A',   bio='Microbiology & Genetics'),
        dict(uid='DOC002',    name_ar='د. سارة النجار',     name_en='Dr. Sara Al-Najjar',       role='دكتور', sec='Section B',   bio='Cell Biology'),
        dict(uid='DOC003',    name_ar='د. حسن المعموري',    name_en='Dr. Hassan Al-Mamouri',    role='دكتور', sec='Section C',   bio='Ecology & Environment'),
        dict(uid='REP001',    name_ar='محمد الزبيدي',       name_en='Mohammed Al-Zubaidi',      role='ممثل',  sec='Section A',   bio='ممثل شعبة A'),
        dict(uid='REP002',    name_ar='نور الهاشمي',        name_en='Noor Al-Hashimi',          role='ممثل',  sec='Section B',   bio='ممثل شعبة B'),
    ]
    # Students
    student_names = [
        ('STU2024001','ياسر الكربلائي','Yasser Al-Karbalaei','Section A'),
        ('STU2024002','زينب العبيدي','Zainab Al-Ubaidi','Section A'),
        ('STU2024003','أحمد الشمري','Ahmed Al-Shammari','Section A'),
        ('STU2024004','مريم الموسوي','Mariam Al-Musawi','Section B'),
        ('STU2024005','حسين البياتي','Hussein Al-Bayati','Section B'),
        ('STU2024006','فاطمة الصدر','Fatima Al-Sadr','Section C'),
        ('STU2024007','عمر الطائي','Omar Al-Taie','Section C'),
        ('STU2024008','سلمى العلوي','Salma Al-Alawi','Section D'),
        ('STU2024009','كرار الجلبي','Karar Al-Jalabi','Section D'),
    ]
    for uid, nar, nen, sec in student_names:
        users.append(dict(uid=uid, name_ar=nar, name_en=nen, role='طالب', sec=sec, bio='طالب في قسم علوم الحياة'))

    user_objs = {}
    for u in users:
        obj = User(
            uid=u['uid'], password_hash=default_pwd,
            name_ar=u['name_ar'], name_en=u['name_en'],
            role=u['role'],
            section_id=secs.get(u['sec']) if u['sec'] else None,
            bio=u.get('bio',''),
        )
        db.session.add(obj); db.session.flush(); user_objs[u['uid']] = obj

    # Channels
    channels = [
        dict(ch_key='gen',  type='ann', name_ar='📢 القناة العامة',       name_en='📢 General Channel',
             desc_ar='الإعلانات الرسمية لقسم علوم الحياة', desc_en='Official announcements',
             owner='COORD001', sec=None, icon='📢', color='#ef4444'),
        dict(ch_key='dm1',  type='doc', name_ar='🦠 الأحياء الدقيقة',     name_en='🦠 Microbiology',
             desc_ar='محاضرات Microbiology – د.علي', desc_en='Microbiology Lectures – Dr.Ali',
             owner='DOC001', sec='Section A', icon='🦠', color='#00d4ff'),
        dict(ch_key='dm2',  type='doc', name_ar='🧬 الوراثة الجزيئية',    name_en='🧬 Molecular Genetics',
             desc_ar='Molecular Genetics – د.علي', desc_en='Molecular Genetics – Dr.Ali',
             owner='DOC001', sec='Section A', icon='🧬', color='#22c55e'),
        dict(ch_key='dm3',  type='doc', name_ar='🔬 بيولوجيا الخلية',     name_en='🔬 Cell Biology',
             desc_ar='Cell Biology – د.سارة', desc_en='Cell Biology – Dr.Sara',
             owner='DOC002', sec='Section B', icon='🔬', color='#a855f7'),
        dict(ch_key='dm4',  type='doc', name_ar='🌿 علم البيئة',           name_en='🌿 Ecology',
             desc_ar='Ecology – د.حسن', desc_en='Ecology – Dr.Hassan',
             owner='DOC003', sec='Section C', icon='🌿', color='#f59e0b'),
        dict(ch_key='rp1',  type='rep', name_ar='📣 إعلانات شعبة A',      name_en='📣 Section A News',
             desc_ar='من ممثل شعبة A', desc_en='Section A Representative',
             owner='REP001', sec='Section A', icon='📣', color='#a855f7'),
        dict(ch_key='rp2',  type='rep', name_ar='📣 إعلانات شعبة B',      name_en='📣 Section B News',
             desc_ar='من ممثل شعبة B', desc_en='Section B Representative',
             owner='REP002', sec='Section B', icon='📣', color='#a855f7'),
    ]
    ch_objs = {}
    for c in channels:
        obj = Channel(
            ch_key=c['ch_key'], ch_type=c['type'],
            name_ar=c['name_ar'], name_en=c['name_en'],
            desc_ar=c['desc_ar'], desc_en=c['desc_en'],
            owner_id=user_objs[c['owner']].id if c['owner'] else None,
            section_id=secs.get(c['sec']) if c['sec'] else None,
            icon=c['icon'], color=c['color'],
        )
        db.session.add(obj); db.session.flush(); ch_objs[c['ch_key']] = obj

    # Sample messages
    def add_msg(ch_key, uid, mtype, text=None, fname=None, url=None):
        db.session.add(Message(
            channel_id=ch_objs[ch_key].id,
            sender_id=user_objs.get(uid).id if uid else None,
            msg_type=mtype, text=text, file_name=fname, link_url=url,
        ))

    add_msg('gen','COORD001','txt','مرحباً بجميع أعضاء القسم في UniPortal 🎉')
    add_msg('dm1','DOC001','txt','مرحباً في قناة الأحياء الدقيقة 🦠\nسأنشر هنا المحاضرات والملفات.')
    add_msg('dm1','DOC001','pdf', fname='Microbiology_Ch7_Biofilm.pdf')
    add_msg('dm1','DOC001','lnk', url='https://www.ncbi.nlm.nih.gov/books/NBK8245/', text='مرجع NCBI')
    add_msg('dm2','DOC001','txt','قناة الوراثة الجزيئية 🧬')
    add_msg('dm2','DOC001','pdf', fname='Genetics_L4_CRISPR.pdf')
    add_msg('dm3','DOC002','txt','قناة بيولوجيا الخلية 🔬 – د.سارة النجار')
    add_msg('dm3','DOC002','pdf', fname='CellBio_Ch5_Membranes.pdf')
    add_msg('dm4','DOC003','txt','قناة علم البيئة 🌿 – د.حسن المعموري')
    add_msg('rp1','REP001','txt','📣 أهلاً بطلاب شعبة A! سأشاركم المستجدات.')
    add_msg('rp2','REP002','txt','📣 قناة إعلانات شعبة B')

    # Sample announcements
    anns = [
        dict(uid='COORD001', title_ar='🎉 أهلاً بكم في UniPortal', content_ar='مرحباً بجميع أعضاء القسم في المنصة الرسمية.', title_en='Welcome to UniPortal', content_en='Welcome to the official platform.', pinned=True, emoji='🎉', color='#0066cc', views=412),
        dict(uid='COORD001', title_ar='📅 جدول الامتحانات النهائية', content_ar='تم إصدار جدول الامتحانات النهائية للفصل الثاني. راجع الملف المرفق.', title_en='Final Exam Schedule Released', content_en='The final exam schedule has been released.', pinned=True, emoji='📅', color='#ef4444', views=380, fname='Final_Exam_Schedule_2026.pdf'),
        dict(uid='COORD001', title_ar='⚠️ آخر موعد لتسديد الرسوم', content_ar='آخر موعد لتسديد الرسوم الجامعية هو 30 أبريل 2026.', title_en='Fee Payment Deadline', content_en='Deadline: April 30, 2026', pinned=False, emoji='⚠️', color='#f59e0b', views=195),
    ]
    for a in anns:
        db.session.add(Announcement(
            author_id=user_objs[a['uid']].id,
            title_ar=a['title_ar'], title_en=a['title_en'],
            content_ar=a['content_ar'], content_en=a['content_en'],
            pinned=a['pinned'], emoji=a['emoji'], color=a['color'],
            views=a.get('views',0),
            file_name=a.get('fname'),
        ))

    db.session.commit()
    print('✅ Database seeded successfully')

with app.app_context():
    try:
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    except Exception as e:
        print(f'Upload folder warning: {e}')
    try:
        os.makedirs('static', exist_ok=True)
    except Exception:
        pass
    try:
        seed_db()
        print('App initialized OK')
    except Exception as e:
        import traceback
        print(f'Init warning: {e}')
        traceback.print_exc()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
