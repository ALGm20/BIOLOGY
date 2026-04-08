"""
UniPortal v3 – جامعة التراث – قسم علوم الحياة
"""
import os, json, re
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

try:
    from pywebpush import webpush, WebPushException
    PUSH_OK = True
except ImportError:
    PUSH_OK = False

# ─── APP CONFIG ────────────────────────────────────────────
app = Flask(__name__)
app.config.update(
    SECRET_KEY               = os.environ.get('SECRET_KEY', 'uniportal-turath-2025-change'),
    SQLALCHEMY_DATABASE_URI  = os.environ.get('DATABASE_URL', 'sqlite:////tmp/uniportal.db')
                               .replace('postgres://', 'postgresql://'),
    SQLALCHEMY_TRACK_MODIFICATIONS = False,
    PERMANENT_SESSION_LIFETIME = timedelta(days=30),
    SESSION_COOKIE_HTTPONLY  = True,
    SESSION_COOKIE_SAMESITE  = 'Lax',
    SESSION_COOKIE_SECURE    = False,
    UPLOAD_FOLDER            = os.environ.get('UPLOAD_FOLDER', '/tmp/uploads'),
    MAX_CONTENT_LENGTH       = 50 * 1024 * 1024,
    VAPID_PUBLIC_KEY         = os.environ.get('VAPID_PUBLIC_KEY',
        'BBOhs6s7-f4lYor-KTFU9nPBwxlgWgxzq-xQnVEtgFJv2Mq8O_G-0fyVdhzEbtlI4rbi4jBwHSLg5uyglQwds60'),
    VAPID_PRIVATE_KEY        = os.environ.get('VAPID_PRIVATE_KEY',
        open(os.path.join(os.path.dirname(__file__), 'vapid_private.pem')).read()
        if os.path.exists(os.path.join(os.path.dirname(__file__), 'vapid_private.pem')) else ''),
    VAPID_CLAIMS             = {'sub': 'mailto:admin@uniportal.edu'},
)

ALLOWED_EXT = {'pdf','png','jpg','jpeg','gif','webp','doc','docx','ppt','pptx'}
db = SQLAlchemy(app)

# ─── ROLES ─────────────────────────────────────────────────
ROLES = {
    'مطور':  {'lv':6,'see_private':True, 'post_gen':True, 'create_ch':True, 'admin':True, 'edit_roles':True,  'edit_students':True},
    'رئيس':  {'lv':5,'see_private':False,'post_gen':True, 'create_ch':False,'admin':True, 'edit_roles':True,  'edit_students':False},
    'مقرر':  {'lv':4,'see_private':False,'post_gen':True, 'create_ch':False,'admin':True, 'edit_roles':True,  'edit_students':False},
    'ممثل':  {'lv':3,'see_private':True, 'post_gen':True, 'create_ch':True, 'admin':False,'edit_roles':False, 'edit_students':False},
    'دكتور': {'lv':2,'see_private':True, 'post_gen':False,'create_ch':True, 'admin':False,'edit_roles':False, 'edit_students':False},
    'طالب':  {'lv':1,'see_private':True, 'post_gen':False,'create_ch':True, 'admin':False,'edit_roles':False, 'edit_students':False},
}

# ─── MODELS ────────────────────────────────────────────────
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
    recovery_code = db.Column(db.String(20))
    online        = db.Column(db.Boolean, default=False)
    active        = db.Column(db.Boolean, default=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    section       = db.relationship('Section', backref='members')

    def rd(self): return ROLES.get(self.role, ROLES['طالب'])
    def can_post_gen(self):  return self.rd()['post_gen']
    def can_create_ch(self): return self.rd()['create_ch']
    def is_admin(self):      return self.rd()['admin']
    def see_private(self):   return self.rd()['see_private']

    def to_dict(self):
        return {
            'id': self.id, 'uid': self.uid,
            'name_ar': self.name_ar, 'name_en': self.name_en,
            'role': self.role,
            'section_id': self.section_id,
            'section_name': self.section.name if self.section else None,
            'bio': self.bio, 'photo_url': self.photo_url,
            'online': self.online, 'active': self.active,
        }

class Section(db.Model):
    id   = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False)

class Channel(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    ch_key     = db.Column(db.String(60), unique=True, nullable=False)
    name_ar    = db.Column(db.String(120), nullable=False)
    name_en    = db.Column(db.String(120))
    desc_ar    = db.Column(db.String(300))
    desc_en    = db.Column(db.String(300))
    ch_type    = db.Column(db.String(20), nullable=False)  # ann|doc|rep
    owner_id   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    section_id = db.Column(db.Integer, db.ForeignKey('section.id'), nullable=True)
    photo_url  = db.Column(db.String(300))
    icon       = db.Column(db.String(10), default='💬')
    color      = db.Column(db.String(10), default='#00d4ff')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    owner      = db.relationship('User', backref='owned_channels')
    section    = db.relationship('Section', backref='channels')

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
    id         = db.Column(db.Integer, primary_key=True)
    channel_id = db.Column(db.Integer, db.ForeignKey('channel.id'), nullable=False)
    sender_id  = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    msg_type   = db.Column(db.String(20), default='txt')  # txt|pdf|img|lnk|sys
    text       = db.Column(db.Text)
    file_path  = db.Column(db.String(400))
    file_name  = db.Column(db.String(200))
    link_url   = db.Column(db.String(500))
    edited     = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    channel    = db.relationship('Channel', backref=db.backref('messages', lazy='dynamic', order_by='Message.created_at'))
    sender     = db.relationship('User', backref='messages')

    def to_dict(self):
        return {
            'id': self.id, 'channel_id': self.channel_id,
            'channel_key': self.channel.ch_key,
            'sender_id': self.sender_id,
            'sender_name': self.sender.name_ar if self.sender else None,
            'sender_role': self.sender.role if self.sender else None,
            'msg_type': self.msg_type,
            'text': self.text, 'file_path': self.file_path,
            'file_name': self.file_name, 'link_url': self.link_url,
            'edited': self.edited,
            'created_at': self.created_at.strftime('%Y-%m-%dT%H:%M:%S'),
        }

class Announcement(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    author_id  = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title_ar   = db.Column(db.String(200), nullable=False)
    title_en   = db.Column(db.String(200))
    content_ar = db.Column(db.Text)
    content_en = db.Column(db.Text)
    file_path  = db.Column(db.String(400))
    file_name  = db.Column(db.String(200))
    link_url   = db.Column(db.String(500))
    link_label = db.Column(db.String(100))
    pinned     = db.Column(db.Boolean, default=False)
    views      = db.Column(db.Integer, default=0)
    emoji      = db.Column(db.String(10), default='📢')
    color      = db.Column(db.String(10), default='#0066cc')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    author     = db.relationship('User', backref='announcements')

    def to_dict(self):
        return {
            'id': self.id, 'author_id': self.author_id,
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

# ─── HELPERS ───────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*a, **kw):
        if 'user_id' not in session:
            return jsonify({'error': 'unauthorized'}), 401
        return f(*a, **kw)
    return decorated

def current_user():
    return User.query.get(session.get('user_id')) if 'user_id' in session else None

def allowed_file(fn):
    return '.' in fn and fn.rsplit('.', 1)[1].lower() in ALLOWED_EXT

def visible_channels(user):
    chs = Channel.query.all()
    rd  = ROLES.get(user.role, ROLES['طالب'])
    result = []
    for ch in chs:
        if ch.ch_type == 'ann':
            result.append(ch); continue
        if not rd['see_private']: continue
        if ch.owner_id == user.id or ch.section_id == user.section_id:
            result.append(ch)
    return result

def can_write(user, ch):
    if ch.ch_type == 'ann': return user.can_post_gen()
    return ch.owner_id == user.id

def notify_all(ch, tar, ten, bar, ben):
    if ch.ch_type == 'ann':
        users = User.query.filter_by(active=True).all()
    else:
        users = User.query.filter(
            (User.id == ch.owner_id) | (User.section_id == ch.section_id)
        ).filter_by(active=True).all()
    for u in users:
        db.session.add(Notification(
            user_id=u.id, title_ar=tar, title_en=ten,
            body_ar=bar, body_en=ben, ch_key=ch.ch_key
        ))
        if PUSH_OK:
            subs = PushSub.query.filter_by(user_id=u.id).all()
            for sub in subs:
                try:
                    webpush(
                        subscription_info=json.loads(sub.sub_json),
                        data=json.dumps({'title': tar, 'body': bar, 'url': '/'}),
                        vapid_private_key=app.config['VAPID_PRIVATE_KEY'],
                        vapid_claims=app.config['VAPID_CLAIMS']
                    )
                except Exception:
                    pass
    db.session.commit()

# ─── AUTH ──────────────────────────────────────────────────
@app.route('/api/login', methods=['POST'])
def api_login():
    d    = request.get_json() or {}
    uid  = d.get('uid', '').strip()
    pwd  = d.get('password', '')
    user = User.query.filter_by(uid=uid, active=True).first()
    if not user:
        return jsonify({'ok': False, 'error': 'الرقم غير موجود في النظام'})
    if not check_password_hash(user.password_hash, pwd):
        return jsonify({'ok': False, 'error': 'كلمة المرور غير صحيحة'})
    session.permanent = True
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
    d = request.get_json() or {}
    if 'name_ar'  in d: u.name_ar  = d['name_ar'][:120]
    if 'name_en'  in d: u.name_en  = d['name_en'][:120]
    if 'bio'      in d: u.bio      = d['bio'][:200]
    if 'password' in d and len(d['password']) >= 4:
        u.password_hash = generate_password_hash(d['password'])
    db.session.commit()
    return jsonify({'ok': True, 'user': u.to_dict()})

@app.route('/api/recover', methods=['POST'])
def api_recover():
    d    = request.get_json() or {}
    uid  = d.get('uid', '').strip()
    code = d.get('recovery_code', '').strip()
    npwd = d.get('new_password', '')
    user = User.query.filter_by(uid=uid, active=True).first()
    if not user or str(user.recovery_code) != str(code):
        return jsonify({'ok': False, 'error': 'بيانات الاسترداد غير صحيحة'})
    if len(npwd) < 4:
        return jsonify({'ok': False, 'error': 'كلمة المرور قصيرة'})
    user.password_hash = generate_password_hash(npwd)
    db.session.commit()
    return jsonify({'ok': True})

# ─── USERS ─────────────────────────────────────────────────
@app.route('/api/users')
@login_required
def api_users():
    u = current_user()
    if not u.is_admin():
        return jsonify({'error': 'forbidden'}), 403
    pg    = request.args.get('page', 1, type=int)
    q_str = request.args.get('q', '')
    q = User.query
    if q_str:
        q = q.filter(User.name_ar.ilike(f'%{q_str}%') | User.uid.ilike(f'%{q_str}%'))
    paged = q.paginate(page=pg, per_page=30)
    return jsonify({'users': [x.to_dict() for x in paged.items],
                    'total': paged.total, 'pages': paged.pages})

@app.route('/api/users/<int:uid>', methods=['PATCH'])
@login_required
def api_update_user(uid):
    me     = current_user()
    target = User.query.get_or_404(uid)
    d      = request.get_json() or {}
    me_rd  = ROLES.get(me.role, {})
    if 'role' in d and d['role'] in ROLES:
        if not me_rd.get('edit_roles'):
            return jsonify({'error': 'forbidden'}), 403
        new_role = d['role']
        # Cannot set مطور unless you ARE مطور
        if new_role == 'مطور' and me.role != 'مطور':
            return jsonify({'error': 'forbidden'}), 403
        # Cannot change طالب role unless مطور
        if target.role == 'طالب' and me.role != 'مطور':
            return jsonify({'error': 'cannot edit student role'}), 403
        target.role = new_role
    if 'active'     in d: target.active     = bool(d['active'])
    if 'section_id' in d: target.section_id = d['section_id'] or None
    db.session.commit()
    return jsonify({'ok': True})

# ─── SECTIONS ──────────────────────────────────────────────
@app.route('/api/sections')
def api_sections():
    return jsonify([{'id': s.id, 'name': s.name} for s in Section.query.all()])

# ─── CHANNELS ──────────────────────────────────────────────
@app.route('/api/channels')
@login_required
def api_channels():
    u   = current_user()
    chs = visible_channels(u)
    out = []
    for ch in chs:
        d2 = ch.to_dict()
        last = ch.messages.order_by(Message.created_at.desc()).first()
        if last:
            if last.msg_type == 'txt': prev = (last.text or '')[:55]
            elif last.msg_type == 'pdf': prev = f"📄 {last.file_name or 'PDF'}"
            elif last.msg_type == 'img': prev = '🖼️ صورة'
            elif last.msg_type == 'lnk': prev = '🔗 رابط'
            else: prev = ''
            d2['last_msg']  = prev
            d2['last_time'] = last.created_at.strftime('%Y-%m-%dT%H:%M:%S')
        else:
            d2['last_msg'] = ''; d2['last_time'] = None
        d2['unread']    = 0
        d2['can_write'] = can_write(u, ch)
        out.append(d2)
    return jsonify(out)

@app.route('/api/channels', methods=['POST'])
@login_required
def api_create_channel():
    u = current_user()
    if not u.can_create_ch():
        return jsonify({'error': 'forbidden'}), 403
    d      = request.get_json() or {}
    ch_type = 'doc' if u.role == 'دكتور' else 'rep' if u.role == 'ممثل' else 'doc'
    import time
    ch = Channel(
        ch_key     = f'ch_{u.id}_{int(time.time())}',
        name_ar    = d.get('name_ar', 'قناة جديدة')[:120],
        name_en    = d.get('name_en', 'New Channel')[:120],
        desc_ar    = d.get('desc_ar', '')[:300],
        desc_en    = d.get('desc_en', '')[:300],
        ch_type    = ch_type,
        owner_id   = u.id,
        section_id = u.section_id,
        icon       = '🔬' if ch_type == 'doc' else '📣',
        color      = '#00d4ff' if ch_type == 'doc' else '#a855f7',
    )
    db.session.add(ch)
    db.session.flush()
    db.session.add(Message(channel_id=ch.id, msg_type='sys',
                            text=f'تم إنشاء القناة بواسطة {u.name_ar}'))
    db.session.commit()
    return jsonify({'ok': True, 'channel': ch.to_dict()})

@app.route('/api/channels/<string:ch_key>/messages')
@login_required
def api_messages(ch_key):
    u  = current_user()
    ch = Channel.query.filter_by(ch_key=ch_key).first_or_404()
    if ch not in visible_channels(u):
        return jsonify({'error': 'forbidden'}), 403
    page = request.args.get('page', 1, type=int)
    msgs = ch.messages.order_by(Message.created_at.asc()).paginate(page=page, per_page=80)
    return jsonify({'messages': [m.to_dict() for m in msgs.items],
                    'has_more': msgs.has_next})

@app.route('/api/channels/<string:ch_key>/messages', methods=['POST'])
@login_required
def api_send_message(ch_key):
    u  = current_user()
    ch = Channel.query.filter_by(ch_key=ch_key).first_or_404()
    if not can_write(u, ch):
        return jsonify({'error': 'forbidden'}), 403
    text     = request.form.get('text', '').strip()
    link_url = request.form.get('link_url', '').strip()
    file     = request.files.get('file')
    msg_type = 'txt'; fp = None; fn = None
    if file and file.filename and allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        fname = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secure_filename(file.filename)}"
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
        fp = f"/uploads/{fname}"; fn = file.filename
        msg_type = 'pdf' if ext == 'pdf' else 'img' if ext in ('png','jpg','jpeg','gif','webp') else 'file'
    elif link_url:
        msg_type = 'lnk'
    elif not text:
        return jsonify({'error': 'empty'}), 400
    msg = Message(channel_id=ch.id, sender_id=u.id, msg_type=msg_type,
                  text=text or None, file_path=fp, file_name=fn,
                  link_url=link_url or None)
    db.session.add(msg)
    db.session.commit()
    preview = text[:60] if text else (fn or link_url or '')
    notify_all(ch,
               f'رسالة في {ch.name_ar}', f'Message in {ch.name_en or ch.name_ar}',
               f'{u.name_ar}: {preview}', f'{u.name_en or u.name_ar}: {preview}')
    return jsonify({'ok': True, 'message': msg.to_dict()})

@app.route('/api/messages/<int:mid>', methods=['PATCH'])
@login_required
def api_edit_message(mid):
    u   = current_user()
    msg = Message.query.get_or_404(mid)
    if msg.sender_id != u.id:
        return jsonify({'error': 'forbidden'}), 403
    d = request.get_json() or {}
    if 'text' in d:
        msg.text   = d['text']
        msg.edited = True
        db.session.commit()
    return jsonify({'ok': True, 'message': msg.to_dict()})

@app.route('/api/messages/<int:mid>', methods=['DELETE'])
@login_required
def api_delete_message(mid):
    u   = current_user()
    msg = Message.query.get_or_404(mid)
    ch  = Channel.query.get(msg.channel_id)
    if msg.sender_id != u.id and ch.owner_id != u.id and not u.is_admin():
        return jsonify({'error': 'forbidden'}), 403
    db.session.delete(msg)
    db.session.commit()
    return jsonify({'ok': True})

# ─── ANNOUNCEMENTS ─────────────────────────────────────────
@app.route('/api/announcements')
@login_required
def api_announcements():
    anns = Announcement.query.order_by(
        Announcement.pinned.desc(), Announcement.created_at.desc()).all()
    return jsonify([a.to_dict() for a in anns])

@app.route('/api/announcements', methods=['POST'])
@login_required
def api_post_ann():
    u = current_user()
    if not u.can_post_gen():
        return jsonify({'error': 'forbidden'}), 403
    tar   = request.form.get('title_ar', '').strip()
    car   = request.form.get('content_ar', '').strip()
    ten   = request.form.get('title_en', '').strip()
    cen   = request.form.get('content_en', '').strip()
    pin   = request.form.get('pinned', '0') == 'True'
    emoji = request.form.get('emoji', '📢')
    color = request.form.get('color', '#0066cc')
    link  = request.form.get('link_url', '').strip()
    llbl  = request.form.get('link_label', '').strip()
    file  = request.files.get('file')
    fp = fn = None
    if file and file.filename and allowed_file(file.filename):
        fname = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secure_filename(file.filename)}"
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
        fp = f"/uploads/{fname}"; fn = file.filename
    ann = Announcement(author_id=u.id, title_ar=tar, title_en=ten or tar,
                       content_ar=car, content_en=cen or car,
                       file_path=fp, file_name=fn,
                       link_url=link or None, link_label=llbl or None,
                       pinned=pin, emoji=emoji, color=color)
    db.session.add(ann)
    db.session.commit()
    for usr in User.query.filter_by(active=True).all():
        db.session.add(Notification(user_id=usr.id,
            title_ar=tar, title_en=ten or tar,
            body_ar=car[:80], body_en=(cen or car)[:80]))
    db.session.commit()
    return jsonify({'ok': True, 'announcement': ann.to_dict()})

@app.route('/api/announcements/<int:aid>', methods=['DELETE'])
@login_required
def api_del_ann(aid):
    u   = current_user()
    ann = Announcement.query.get_or_404(aid)
    if ann.author_id != u.id and not u.is_admin():
        return jsonify({'error': 'forbidden'}), 403
    db.session.delete(ann)
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/announcements/<int:aid>/pin', methods=['POST'])
@login_required
def api_pin_ann(aid):
    u   = current_user()
    ann = Announcement.query.get_or_404(aid)
    ann.pinned = not ann.pinned
    db.session.commit()
    return jsonify({'ok': True, 'pinned': ann.pinned})

@app.route('/api/announcements/<int:aid>/view', methods=['POST'])
@login_required
def api_view_ann(aid):
    ann = Announcement.query.get_or_404(aid)
    ann.views += 1
    db.session.commit()
    return jsonify({'ok': True})

# ─── NOTIFICATIONS ─────────────────────────────────────────
@app.route('/api/notifications')
@login_required
def api_notifs():
    u = current_user()
    ns = Notification.query.filter_by(user_id=u.id)\
           .order_by(Notification.created_at.desc()).limit(60).all()
    return jsonify({'notifications': [n.to_dict() for n in ns],
                    'unread': Notification.query.filter_by(user_id=u.id, is_read=False).count()})

@app.route('/api/notifications/read_all', methods=['POST'])
@login_required
def api_read_all():
    u = current_user()
    Notification.query.filter_by(user_id=u.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/notifications/<int:nid>/read', methods=['POST'])
@login_required
def api_read_one(nid):
    u = current_user()
    n = Notification.query.filter_by(id=nid, user_id=u.id).first_or_404()
    n.is_read = True
    db.session.commit()
    return jsonify({'ok': True})

# ─── PUSH ──────────────────────────────────────────────────
@app.route('/api/push/subscribe', methods=['POST'])
@login_required
def api_push_sub():
    u  = current_user()
    sj = json.dumps(request.get_json() or {})
    ex = PushSub.query.filter_by(user_id=u.id).first()
    if ex: ex.sub_json = sj
    else:  db.session.add(PushSub(user_id=u.id, sub_json=sj))
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/push/vapid-key')
def api_vapid():
    return jsonify({'key': app.config['VAPID_PUBLIC_KEY']})

# ─── UPLOADS ───────────────────────────────────────────────
@app.route('/api/upload-photo', methods=['POST'])
@login_required
def api_upload_photo():
    u    = current_user()
    file = request.files.get('photo')
    if not file or not allowed_file(file.filename):
        return jsonify({'error': 'invalid'}), 400
    ext = file.filename.rsplit('.', 1)[1]
    fn  = f"photo_{u.id}_{int(datetime.now().timestamp())}.{ext}"
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], fn))
    u.photo_url = f'/uploads/{fn}'
    db.session.commit()
    return jsonify({'ok': True, 'url': u.photo_url})

@app.route('/api/upload-channel-photo', methods=['POST'])
@login_required
def api_ch_photo():
    u      = current_user()
    ch_key = request.form.get('ch_key')
    ch     = Channel.query.filter_by(ch_key=ch_key).first_or_404()
    if ch.owner_id != u.id and not u.is_admin():
        return jsonify({'error': 'forbidden'}), 403
    file = request.files.get('photo')
    if not file or not allowed_file(file.filename):
        return jsonify({'error': 'invalid'}), 400
    ext = file.filename.rsplit('.', 1)[1]
    fn  = f"ch_{ch.id}_{int(datetime.now().timestamp())}.{ext}"
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], fn))
    ch.photo_url = f'/uploads/{fn}'
    db.session.commit()
    return jsonify({'ok': True, 'url': ch.photo_url})

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ─── STATS ─────────────────────────────────────────────────
@app.route('/api/stats')
@login_required
def api_stats():
    u = current_user()
    if not u.is_admin():
        return jsonify({'error': 'forbidden'}), 403
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
        'by_role':  [{'role': r, 'count': c} for r, c in by_role],
        'by_section':[{'name': n, 'count': c} for n, c in by_sec],
    })

# ─── STATIC ────────────────────────────────────────────────
@app.route('/health')
def health():
    return {'status': 'ok', 'app': 'UniPortal v3'}, 200

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

# ─── SEED ──────────────────────────────────────────────────
def seed():
    db.create_all()
    if Section.query.first():
        return

    # Sections
    secs = {}
    for name in ['Section A', 'Section B', 'Section C', 'Section D']:
        s = Section(name=name)
        db.session.add(s)
        db.session.flush()
        secs[name] = s.id

    def mkuser(uid, name_ar, name_en, role, sec, pwd, recovery, bio=''):
        db.session.add(User(
            uid=uid, password_hash=generate_password_hash(pwd),
            name_ar=name_ar, name_en=name_en, role=role,
            section_id=secs.get(sec) if sec else None,
            bio=bio, recovery_code=recovery, active=True
        ))

    # Staff
    mkuser('YASSER_DEV','ياسر محمد مظلوم','Yasser Mohammed Mazloom','مطور', None,'dev@uniportal2025','00000','مطور النظام – جامعة التراث')
    mkuser('HEAD001','أ.د. كريم الجبوري','Prof. Kareem Al-Jabbouri','رئيس',None,'1234','11111','رئيس قسم علوم الحياة')
    mkuser('COORD001','د. منى الكاظمي','Dr. Mona Al-Kadhimi','مقرر',None,'1234','22222','مقررة قسم علوم الحياة')
    mkuser('DOC001','د. علي الحسيني','Dr. Ali Al-Husseini','دكتور','Section A','1234','33333','Microbiology & Genetics')
    mkuser('DOC002','د. سارة النجار','Dr. Sara Al-Najjar','دكتور','Section B','1234','44444','Cell Biology')
    mkuser('DOC003','د. حسن المعموري','Dr. Hassan Al-Mamouri','دكتور','Section C','1234','55555','Ecology')
    mkuser('REP001','محمد الزبيدي','Mohammed Al-Zubaidi','ممثل','Section A','1234','66666','ممثل شعبة A')
    mkuser('REP002','نور الهاشمي','Noor Al-Hashimi','ممثل','Section B','1234','77777','ممثل شعبة B')
    db.session.flush()

    # 395 students from university data
    try:
        from students_data import STUDENTS
        print(f'Adding {len(STUDENTS)} students...')
        for exam_id, name_ar, pwd, recovery in STUDENTS:
            if not User.query.filter_by(uid=exam_id).first():
                db.session.add(User(
                    uid=exam_id, password_hash=generate_password_hash(pwd),
                    name_ar=name_ar, name_en=name_ar, role='طالب',
                    section_id=secs.get('Section A'),
                    bio='طالب – قسم علوم الحياة – جامعة التراث',
                    recovery_code=recovery, active=True
                ))
        db.session.flush()
        print('Students added OK')
    except ImportError:
        print('students_data.py not found, skipping students')

    # Get user ids
    def uid_to_id(uid):
        u = User.query.filter_by(uid=uid).first()
        return u.id if u else None

    # Channels
    channels = [
        ('uni_ann','ann','📢 الإعلانات الجامعية','📢 University Announcements',
         'إعلانات رئيس القسم الرسمية','Official announcements from Head','HEAD001',None,'📢','#fbbf24'),
        ('gen','ann','📣 التبليغات العامة','📣 General Announcements',
         'تبليغات عامة لجميع أعضاء القسم','General announcements for all members','COORD001',None,'📣','#ef4444'),
        ('dm1','doc','🦠 الأحياء الدقيقة','🦠 Microbiology',
         'محاضرات Microbiology – د.علي','Microbiology – Dr.Ali','DOC001','Section A','🦠','#00d4ff'),
        ('dm2','doc','🧬 الوراثة الجزيئية','🧬 Molecular Genetics',
         'Molecular Genetics – د.علي','Molecular Genetics – Dr.Ali','DOC001','Section A','🧬','#22c55e'),
        ('dm3','doc','🔬 بيولوجيا الخلية','🔬 Cell Biology',
         'Cell Biology – د.سارة','Cell Biology – Dr.Sara','DOC002','Section B','🔬','#a855f7'),
        ('dm4','doc','🌿 علم البيئة','🌿 Ecology',
         'Ecology – د.حسن','Ecology – Dr.Hassan','DOC003','Section C','🌿','#f59e0b'),
        ('rp1','rep','📣 إعلانات شعبة A','📣 Section A News',
         'من ممثل شعبة A','Section A Representative','REP001','Section A','📣','#a855f7'),
        ('rp2','rep','📣 إعلانات شعبة B','📣 Section B News',
         'من ممثل شعبة B','Section B Representative','REP002','Section B','📣','#a855f7'),
    ]
    ch_objs = {}
    for ck, ct, nar, nen, dar, den, own, sec, icon, color in channels:
        ch = Channel(
            ch_key=ck, ch_type=ct, name_ar=nar, name_en=nen,
            desc_ar=dar, desc_en=den,
            owner_id=uid_to_id(own),
            section_id=secs.get(sec) if sec else None,
            icon=icon, color=color
        )
        db.session.add(ch)
        db.session.flush()
        ch_objs[ck] = ch

    def add_msg(ck, uid, mtype, text=None, fname=None, url=None):
        db.session.add(Message(
            channel_id=ch_objs[ck].id,
            sender_id=uid_to_id(uid),
            msg_type=mtype, text=text, file_name=fname, link_url=url
        ))

    # Sample messages
    add_msg('gen','COORD001','txt','مرحباً بجميع أعضاء القسم في UniPortal 🎉\nقسم علوم الحياة – جامعة التراث – كلية العلوم')
    add_msg('dm1','DOC001','txt','🦠 قناة مادة الأحياء الدقيقة\nسأنشر هنا المحاضرات والملفات والمصادر العلمية')
    add_msg('dm1','DOC001','pdf',fname='Microbiology_Ch7_Biofilm.pdf')
    add_msg('dm1','DOC001','lnk',url='https://www.ncbi.nlm.nih.gov/books/NBK8245/',text='مرجع NCBI – Microbiology')
    add_msg('dm2','DOC001','txt','🧬 قناة الوراثة الجزيئية – د.علي الحسيني')
    add_msg('dm2','DOC001','pdf',fname='Genetics_L4_CRISPR_Cas9.pdf')
    add_msg('dm3','DOC002','txt','🔬 بيولوجيا الخلية – د.سارة النجار')
    add_msg('dm3','DOC002','pdf',fname='CellBio_Ch5_Membranes.pdf')
    add_msg('dm4','DOC003','txt','🌿 علم البيئة – د.حسن المعموري')
    add_msg('rp1','REP001','txt','📣 أهلاً بطلاب شعبة A!\nسأشاركم المستجدات والأخبار المهمة')
    add_msg('rp2','REP002','txt','📣 قناة إعلانات شعبة B')

    # Sample announcements
    anns = [
        ('HEAD001','🎉 أهلاً بكم في UniPortal','Welcome to UniPortal',
         'مرحباً بجميع أعضاء قسم علوم الحياة في المنصة الرسمية لجامعة التراث.',
         'Welcome to the official platform of Life Sciences Dept.',True,'🎉','#0066cc',412),
        ('COORD001','📅 جدول الامتحانات النهائية','Final Exam Schedule',
         'تم إصدار جدول الامتحانات النهائية للفصل الثاني. راجع الملف المرفق للتفاصيل.',
         'Final exam schedule released. Check attached file.',True,'📅','#ef4444',380),
        ('COORD001','⚠️ آخر موعد لتسديد الرسوم','Fee Payment Deadline',
         'آخر موعد لتسديد الرسوم الجامعية هو 30 أبريل 2026. مراجعة الدائرة المالية.',
         'Deadline: April 30, 2026. Visit Finance Dept.',False,'⚠️','#f59e0b',195),
    ]
    for ow, tar, ten, car, cen, pin, emoji, color, views in anns:
        db.session.add(Announcement(
            author_id=uid_to_id(ow), title_ar=tar, title_en=ten,
            content_ar=car, content_en=cen, pinned=pin,
            emoji=emoji, color=color, views=views
        ))

    db.session.commit()
    total = User.query.count()
    print(f'✅ Seeded: {total} users, {len(channels)} channels')

# ─── STARTUP ───────────────────────────────────────────────
with app.app_context():
    try:
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    except Exception:
        pass
    try:
        os.makedirs('static', exist_ok=True)
    except Exception:
        pass
    try:
        seed()
    except Exception as e:
        import traceback
        print(f'Seed warning: {e}')
        traceback.print_exc()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
