"""UniPortal v5 – جامعة التراث"""
import os, json, time
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

try:
    from pywebpush import webpush, WebPushException
    PUSH_OK = True
except:
    PUSH_OK = False

app = Flask(__name__)
app.config.update(
    SECRET_KEY              = os.environ.get('SECRET_KEY', 'uniportal-v5-turath-2025'),
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL',
        'sqlite:////tmp/up5.db').replace('postgres://', 'postgresql://'),
    SQLALCHEMY_TRACK_MODIFICATIONS = False,
    UPLOAD_FOLDER           = os.environ.get('UPLOAD_FOLDER', '/tmp/uploads'),
    MAX_CONTENT_LENGTH      = 50 * 1024 * 1024,
    VAPID_PUBLIC_KEY        = os.environ.get('VAPID_PUBLIC_KEY',
        'BBOhs6s7-f4lYor-KTFU9nPBwxlgWgxzq-xQnVEtgFJv2Mq8O_G-0fyVdhzEbtlI4rbi4jBwHSLg5uyglQwds60'),
    VAPID_PRIVATE_KEY       = os.environ.get('VAPID_PRIVATE_KEY', ''),
    VAPID_CLAIMS            = {'sub': 'mailto:dev@uniportal.edu'},
)

# Load VAPID private key
_vpem = os.path.join(os.path.dirname(__file__), 'vapid_private.pem')
if not app.config['VAPID_PRIVATE_KEY'] and os.path.exists(_vpem):
    app.config['VAPID_PRIVATE_KEY'] = open(_vpem).read()

ALLOWED = {'pdf','png','jpg','jpeg','gif','webp','doc','docx','ppt','pptx'}
db = SQLAlchemy(app)

# ─── ROLES ───────────────────────────────────────────────────
ROLES = {
    'مطور':  {'lv':6,'see_private':True, 'post_gen':True, 'create_ch':True, 'admin':True},
    'رئيس':  {'lv':5,'see_private':False,'post_gen':True, 'create_ch':False,'admin':True},
    'مقرر':  {'lv':4,'see_private':False,'post_gen':True, 'create_ch':False,'admin':True},
    'ممثل':  {'lv':3,'see_private':True, 'post_gen':True, 'create_ch':True, 'admin':False},
    'دكتور': {'lv':2,'see_private':True, 'post_gen':False,'create_ch':True, 'admin':False},
    'طالب':  {'lv':1,'see_private':True, 'post_gen':False,'create_ch':True, 'admin':False},
}

# ─── MODELS ──────────────────────────────────────────────────
class User(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    uid           = db.Column(db.String(40), unique=True, nullable=False)
    pwd_hash      = db.Column(db.String(256), nullable=False)
    name_ar       = db.Column(db.String(120), nullable=False)
    name_en       = db.Column(db.String(120))
    role          = db.Column(db.String(20), nullable=False, default='طالب')
    section_id    = db.Column(db.Integer, db.ForeignKey('section.id'), nullable=True)
    bio           = db.Column(db.String(200))
    photo_url     = db.Column(db.String(300))
    recovery_code = db.Column(db.String(20))
    active        = db.Column(db.Boolean, default=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    section       = db.relationship('Section', backref='members')

    def rd(self): return ROLES.get(self.role, ROLES['طالب'])
    def to_dict(self):
        return {'id':self.id,'uid':self.uid,'name_ar':self.name_ar,'name_en':self.name_en,
                'role':self.role,'section_id':self.section_id,
                'section_name':self.section.name if self.section else None,
                'bio':self.bio,'photo_url':self.photo_url,'active':self.active,
                'role_lv':self.rd()['lv']}

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
    ch_type    = db.Column(db.String(20), nullable=False)
    owner_id   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    section_id = db.Column(db.Integer, db.ForeignKey('section.id'), nullable=True)
    photo_url  = db.Column(db.String(300))
    icon       = db.Column(db.String(10), default='💬')
    color      = db.Column(db.String(10), default='#00d4ff')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    owner      = db.relationship('User', backref='owned_channels')
    section    = db.relationship('Section', backref='channels')

    def to_dict(self):
        return {'id':self.id,'ch_key':self.ch_key,'name_ar':self.name_ar,'name_en':self.name_en,
                'desc_ar':self.desc_ar,'desc_en':self.desc_en,'ch_type':self.ch_type,
                'owner_id':self.owner_id,'owner_name':self.owner.name_ar if self.owner else None,
                'section_id':self.section_id,'section_name':self.section.name if self.section else None,
                'photo_url':self.photo_url,'icon':self.icon,'color':self.color}

class Message(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    channel_id = db.Column(db.Integer, db.ForeignKey('channel.id'), nullable=False)
    sender_id  = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    msg_type   = db.Column(db.String(20), default='txt')
    text       = db.Column(db.Text)
    file_path  = db.Column(db.String(400))
    file_name  = db.Column(db.String(200))
    link_url   = db.Column(db.String(500))
    edited     = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    channel    = db.relationship('Channel',
                     backref=db.backref('messages', lazy='dynamic', order_by='Message.created_at'))
    sender     = db.relationship('User', backref='messages')

    def to_dict(self):
        return {'id':self.id,'channel_id':self.channel_id,'channel_key':self.channel.ch_key,
                'sender_id':self.sender_id,
                'sender_name':self.sender.name_ar if self.sender else None,
                'sender_role':self.sender.role if self.sender else None,
                'msg_type':self.msg_type,'text':self.text,'file_path':self.file_path,
                'file_name':self.file_name,'link_url':self.link_url,'edited':self.edited,
                'created_at':self.created_at.strftime('%Y-%m-%dT%H:%M:%S')}

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
        return {'id':self.id,'author_id':self.author_id,
                'author_name':self.author.name_ar if self.author else None,
                'title_ar':self.title_ar,'title_en':self.title_en,
                'content_ar':self.content_ar,'content_en':self.content_en,
                'file_path':self.file_path,'file_name':self.file_name,
                'link_url':self.link_url,'link_label':self.link_label,
                'pinned':self.pinned,'views':self.views,'emoji':self.emoji,'color':self.color,
                'created_at':self.created_at.strftime('%Y-%m-%dT%H:%M:%S')}

class PushSub(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    user_id  = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sub_json = db.Column(db.Text, nullable=False)

class Notif(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title_ar   = db.Column(db.String(200))
    body_ar    = db.Column(db.String(400))
    ch_key     = db.Column(db.String(60))
    is_read    = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {'id':self.id,'title_ar':self.title_ar,'body_ar':self.body_ar,
                'ch_key':self.ch_key,'is_read':self.is_read,
                'created_at':self.created_at.strftime('%Y-%m-%dT%H:%M:%S')}

# ─── TOKEN AUTH (localStorage-based) ─────────────────────────
# Simple token = base64(user_id:uid:timestamp) stored in localStorage
import base64, hashlib

def make_token(user):
    raw = f"{user.id}:{user.uid}:{int(time.time())}"
    sig = hashlib.sha256(f"{raw}{app.config['SECRET_KEY']}".encode()).hexdigest()[:16]
    return base64.urlsafe_b64encode(f"{raw}:{sig}".encode()).decode()

def verify_token(token):
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        parts   = decoded.split(':')
        if len(parts) != 4:
            return None
        uid_n, uid_str, ts, sig = parts
        # Check signature
        raw  = f"{uid_n}:{uid_str}:{ts}"
        expected = hashlib.sha256(f"{raw}{app.config['SECRET_KEY']}".encode()).hexdigest()[:16]
        if sig != expected:
            return None
        # Token valid for 90 days
        if int(time.time()) - int(ts) > 90 * 86400:
            return None
        return User.query.get(int(uid_n))
    except:
        return None

def auth_required(f):
    @wraps(f)
    def decorated(*a, **kw):
        token = request.headers.get('X-Auth-Token', '')
        if not token:
            return jsonify({'error': 'unauthorized'}), 401
        user = verify_token(token)
        if not user or not user.active:
            return jsonify({'error': 'unauthorized'}), 401
        request.current_user = user
        return f(*a, **kw)
    return decorated

def cu():
    return getattr(request, 'current_user', None)

# ─── VISIBILITY ──────────────────────────────────────────────
def visible_chs(user):
    rd = ROLES.get(user.role, ROLES['طالب'])
    out = []
    for ch in Channel.query.all():
        if ch.ch_type == 'ann':
            out.append(ch); continue
        if not rd['see_private']:
            continue
        if ch.owner_id == user.id or ch.section_id == user.section_id:
            out.append(ch)
    return out

def can_write(user, ch):
    if ch.ch_type == 'ann':
        return ROLES.get(user.role, {}).get('post_gen', False)
    return ch.owner_id == user.id

# ─── PUSH ────────────────────────────────────────────────────
def push_to_user(uid, title, body):
    subs = PushSub.query.filter_by(user_id=uid).all()
    if not subs or not PUSH_OK or not app.config['VAPID_PRIVATE_KEY']:
        return
    payload = json.dumps({'title': title, 'body': body, 'url': '/'})
    dead = []
    for sub in subs:
        try:
            webpush(subscription_info=json.loads(sub.sub_json), data=payload,
                    vapid_private_key=app.config['VAPID_PRIVATE_KEY'],
                    vapid_claims=app.config['VAPID_CLAIMS'])
        except:
            dead.append(sub.id)
    if dead:
        PushSub.query.filter(PushSub.id.in_(dead)).delete()
        db.session.commit()

def notify_members(ch, title, body):
    if ch.ch_type == 'ann':
        users = User.query.filter_by(active=True).all()
    else:
        q = User.query.filter(
            (User.id == ch.owner_id) | (User.section_id == ch.section_id)
        ).filter_by(active=True)
        users = q.all()
    for u in users:
        db.session.add(Notif(user_id=u.id, title_ar=title, body_ar=body, ch_key=ch.ch_key))
        push_to_user(u.id, title, body)
    db.session.commit()

def allowed_file(fn):
    return '.' in fn and fn.rsplit('.', 1)[1].lower() in ALLOWED

# ─── AUTH ROUTES ─────────────────────────────────────────────
@app.route('/api/login', methods=['POST'])
def api_login():
    d    = request.get_json() or {}
    uid  = (d.get('uid') or '').strip().upper()
    pwd  = d.get('password', '')
    if not uid or not pwd:
        return jsonify({'ok': False, 'error': 'أدخل الرقم وكلمة المرور'})
    user = User.query.filter_by(uid=uid, active=True).first()
    if not user:
        return jsonify({'ok': False, 'error': 'الرقم غير موجود في النظام'})
    if not check_password_hash(user.pwd_hash, pwd):
        return jsonify({'ok': False, 'error': 'كلمة المرور غير صحيحة'})
    token = make_token(user)
    return jsonify({'ok': True, 'token': token, 'user': user.to_dict()})

@app.route('/api/me')
@auth_required
def api_me():
    return jsonify(cu().to_dict())

@app.route('/api/me', methods=['PATCH'])
@auth_required
def api_update_me():
    u = cu()
    d = request.get_json() or {}
    if 'name_ar'  in d: u.name_ar = d['name_ar'][:120]
    if 'bio'      in d: u.bio     = d['bio'][:200]
    if 'password' in d and len(str(d['password'])) >= 4:
        u.pwd_hash = generate_password_hash(d['password'])
    db.session.commit()
    return jsonify({'ok': True, 'user': u.to_dict()})

@app.route('/api/recover', methods=['POST'])
def api_recover():
    d    = request.get_json() or {}
    uid  = (d.get('uid') or '').strip().upper()
    code = str(d.get('recovery_code', '')).strip()
    npwd = str(d.get('new_password', ''))
    user = User.query.filter_by(uid=uid, active=True).first()
    if not user or str(user.recovery_code) != code:
        return jsonify({'ok': False, 'error': 'بيانات الاسترداد غير صحيحة'})
    if len(npwd) < 4:
        return jsonify({'ok': False, 'error': 'كلمة المرور قصيرة'})
    user.pwd_hash = generate_password_hash(npwd)
    db.session.commit()
    return jsonify({'ok': True})

# ─── USERS ───────────────────────────────────────────────────
@app.route('/api/users')
@auth_required
def api_users():
    u = cu()
    if not ROLES.get(u.role, {}).get('admin'):
        return jsonify({'error': 'forbidden'}), 403
    pg  = request.args.get('page', 1, type=int)
    q   = request.args.get('q', '')
    qry = User.query
    if q:
        qry = qry.filter(User.name_ar.ilike(f'%{q}%') | User.uid.ilike(f'%{q}%'))
    paged = qry.paginate(page=pg, per_page=30)
    return jsonify({'users': [x.to_dict() for x in paged.items],
                    'total': paged.total, 'pages': paged.pages})

@app.route('/api/users/<int:uid>', methods=['PATCH'])
@auth_required
def api_update_user(uid):
    me     = cu()
    me_lv  = ROLES.get(me.role, {}).get('lv', 0)
    target = User.query.get_or_404(uid)
    d      = request.get_json() or {}
    if 'role' in d and d['role'] in ROLES:
        new_lv = ROLES[d['role']]['lv']
        # Only مطور can set مطور or edit طالب
        if d['role'] == 'مطور' and me.role != 'مطور':
            return jsonify({'error': 'forbidden'}), 403
        if target.role == 'طالب' and me.role != 'مطور':
            return jsonify({'error': 'forbidden'}), 403
        if not ROLES.get(me.role, {}).get('admin'):
            return jsonify({'error': 'forbidden'}), 403
        target.role = d['role']
    if 'active'     in d: target.active     = bool(d['active'])
    if 'section_id' in d: target.section_id = d['section_id'] or None
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/sections')
def api_sections():
    return jsonify([{'id': s.id, 'name': s.name} for s in Section.query.all()])

# ─── CHANNELS ────────────────────────────────────────────────
@app.route('/api/channels')
@auth_required
def api_channels():
    u   = cu()
    chs = visible_chs(u)
    out = []
    for ch in chs:
        d2 = ch.to_dict()
        last = ch.messages.order_by(Message.created_at.desc()).first()
        if last:
            p = last.text[:55] if last.text else {'pdf':'📄 PDF','img':'🖼️ صورة','lnk':'🔗 رابط'}.get(last.msg_type, '')
            d2['last_msg']  = p
            d2['last_time'] = last.created_at.strftime('%Y-%m-%dT%H:%M:%S')
        else:
            d2['last_msg'] = ''; d2['last_time'] = None
        d2['can_write'] = can_write(u, ch)
        out.append(d2)
    return jsonify(out)

@app.route('/api/channels', methods=['POST'])
@auth_required
def api_create_channel():
    u  = cu()
    if not ROLES.get(u.role, {}).get('create_ch'):
        return jsonify({'error': 'forbidden'}), 403
    d  = request.get_json() or {}
    ct = 'doc' if u.role == 'دكتور' else 'rep'
    ch = Channel(
        ch_key     = f'ch_{u.id}_{int(time.time())}',
        name_ar    = d.get('name_ar', 'قناة جديدة')[:120],
        name_en    = d.get('name_en', 'New Channel')[:120],
        desc_ar    = d.get('desc_ar', '')[:300],
        desc_en    = d.get('desc_en', '')[:300],
        ch_type    = ct, owner_id=u.id, section_id=u.section_id,
        icon='🔬' if ct=='doc' else '📣',
        color='#00d4ff' if ct=='doc' else '#a855f7'
    )
    db.session.add(ch); db.session.flush()
    db.session.add(Message(channel_id=ch.id, msg_type='sys',
                            text=f'تم إنشاء القناة بواسطة {u.name_ar}'))
    db.session.commit()
    return jsonify({'ok': True, 'channel': ch.to_dict()})

@app.route('/api/channels/<string:ck>/messages')
@auth_required
def api_msgs(ck):
    u  = cu()
    ch = Channel.query.filter_by(ch_key=ck).first_or_404()
    if ch not in visible_chs(u):
        return jsonify({'error': 'forbidden'}), 403
    pg   = request.args.get('page', 1, type=int)
    msgs = ch.messages.order_by(Message.created_at.asc()).paginate(page=pg, per_page=80)
    return jsonify({'messages': [m.to_dict() for m in msgs.items], 'has_more': msgs.has_next})

@app.route('/api/channels/<string:ck>/messages', methods=['POST'])
@auth_required
def api_send(ck):
    u  = cu()
    ch = Channel.query.filter_by(ch_key=ck).first_or_404()
    if not can_write(u, ch):
        return jsonify({'error': 'forbidden'}), 403
    text = request.form.get('text', '').strip()
    link = request.form.get('link_url', '').strip()
    file = request.files.get('file')
    mt   = 'txt'; fp = fn = None
    if file and file.filename and allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        fname = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secure_filename(file.filename)}"
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
        fp = f"/uploads/{fname}"; fn = file.filename
        mt = 'pdf' if ext == 'pdf' else 'img' if ext in ('png','jpg','jpeg','gif','webp') else 'file'
    elif link: mt = 'lnk'
    elif not text: return jsonify({'error': 'empty'}), 400
    msg = Message(channel_id=ch.id, sender_id=u.id, msg_type=mt,
                  text=text or None, file_path=fp, file_name=fn, link_url=link or None)
    db.session.add(msg); db.session.commit()
    preview = text[:60] if text else (fn or link or '')
    notify_members(ch, f'رسالة في {ch.name_ar}', f'{u.name_ar}: {preview}')
    return jsonify({'ok': True, 'message': msg.to_dict()})

@app.route('/api/messages/<int:mid>', methods=['PATCH'])
@auth_required
def api_edit_msg(mid):
    u   = cu()
    msg = Message.query.get_or_404(mid)
    if msg.sender_id != u.id:
        return jsonify({'error': 'forbidden'}), 403
    d = request.get_json() or {}
    if 'text' in d: msg.text = d['text']; msg.edited = True; db.session.commit()
    return jsonify({'ok': True, 'message': msg.to_dict()})

@app.route('/api/messages/<int:mid>', methods=['DELETE'])
@auth_required
def api_del_msg(mid):
    u   = cu()
    msg = Message.query.get_or_404(mid)
    ch  = Channel.query.get(msg.channel_id)
    if msg.sender_id != u.id and ch.owner_id != u.id and not ROLES.get(u.role, {}).get('admin'):
        return jsonify({'error': 'forbidden'}), 403
    db.session.delete(msg); db.session.commit()
    return jsonify({'ok': True})

# ─── ANNOUNCEMENTS ───────────────────────────────────────────
@app.route('/api/announcements')
@auth_required
def api_anns():
    anns = Announcement.query.order_by(
        Announcement.pinned.desc(), Announcement.created_at.desc()).all()
    return jsonify([a.to_dict() for a in anns])

@app.route('/api/announcements', methods=['POST'])
@auth_required
def api_post_ann():
    u = cu()
    if not ROLES.get(u.role, {}).get('post_gen'):
        return jsonify({'error': 'forbidden'}), 403
    tar  = request.form.get('title_ar', '').strip()
    car  = request.form.get('content_ar', '').strip()
    pin  = request.form.get('pinned', 'false').lower() == 'true'
    link = request.form.get('link_url', '').strip()
    file = request.files.get('file')
    fp = fn = None
    if file and file.filename and allowed_file(file.filename):
        fname = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secure_filename(file.filename)}"
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
        fp = f"/uploads/{fname}"; fn = file.filename
    ann = Announcement(author_id=u.id, title_ar=tar, title_en=tar,
                       content_ar=car, content_en=car, pinned=pin,
                       file_path=fp, file_name=fn, link_url=link or None,
                       emoji='📢', color='#0066cc')
    db.session.add(ann); db.session.commit()
    for usr in User.query.filter_by(active=True).all():
        db.session.add(Notif(user_id=usr.id, title_ar=tar, body_ar=car[:80]))
        push_to_user(usr.id, tar, car[:80])
    db.session.commit()
    return jsonify({'ok': True, 'announcement': ann.to_dict()})

@app.route('/api/announcements/<int:aid>', methods=['DELETE'])
@auth_required
def api_del_ann(aid):
    u = cu(); ann = Announcement.query.get_or_404(aid)
    if ann.author_id != u.id and not ROLES.get(u.role, {}).get('admin'):
        return jsonify({'error': 'forbidden'}), 403
    db.session.delete(ann); db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/announcements/<int:aid>/pin', methods=['POST'])
@auth_required
def api_pin_ann(aid):
    ann = Announcement.query.get_or_404(aid)
    ann.pinned = not ann.pinned; db.session.commit()
    return jsonify({'ok': True, 'pinned': ann.pinned})

# ─── NOTIFICATIONS ───────────────────────────────────────────
@app.route('/api/notifications')
@auth_required
def api_notifs():
    u  = cu()
    ns = Notif.query.filter_by(user_id=u.id)\
           .order_by(Notif.created_at.desc()).limit(60).all()
    unread = Notif.query.filter_by(user_id=u.id, is_read=False).count()
    return jsonify({'notifications': [n.to_dict() for n in ns], 'unread': unread})

@app.route('/api/notifications/read_all', methods=['POST'])
@auth_required
def api_read_all():
    Notif.query.filter_by(user_id=cu().id, is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/notifications/<int:nid>/read', methods=['POST'])
@auth_required
def api_read_one(nid):
    n = Notif.query.filter_by(id=nid, user_id=cu().id).first_or_404()
    n.is_read = True; db.session.commit()
    return jsonify({'ok': True})

# ─── PUSH SUBSCRIBE ──────────────────────────────────────────
@app.route('/api/push/subscribe', methods=['POST'])
@auth_required
def api_push_sub():
    u = cu()
    sj = json.dumps(request.get_json() or {})
    ex = PushSub.query.filter_by(user_id=u.id).first()
    if ex: ex.sub_json = sj
    else:  db.session.add(PushSub(user_id=u.id, sub_json=sj))
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/push/key')
def api_push_key():
    return jsonify({'key': app.config['VAPID_PUBLIC_KEY']})

# ─── UPLOADS ─────────────────────────────────────────────────
@app.route('/api/upload-photo', methods=['POST'])
@auth_required
def api_upload_photo():
    u = cu(); file = request.files.get('photo')
    if not file or not allowed_file(file.filename):
        return jsonify({'error': 'invalid'}), 400
    ext = file.filename.rsplit('.', 1)[1]
    fn  = f"photo_{u.id}_{int(time.time())}.{ext}"
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], fn))
    u.photo_url = f'/uploads/{fn}'; db.session.commit()
    return jsonify({'ok': True, 'url': u.photo_url})

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ─── STATS ───────────────────────────────────────────────────
@app.route('/api/stats')
@auth_required
def api_stats():
    u = cu()
    if not ROLES.get(u.role, {}).get('admin'):
        return jsonify({'error': 'forbidden'}), 403
    from sqlalchemy import func
    by_role = db.session.query(User.role, func.count(User.id))\
                .filter_by(active=True).group_by(User.role).all()
    return jsonify({
        'total_users': User.query.filter_by(active=True).count(),
        'total_chs':   Channel.query.count(),
        'total_msgs':  Message.query.count(),
        'by_role': [{'role': r, 'count': c} for r, c in by_role]
    })

# ─── STATIC ──────────────────────────────────────────────────
@app.route('/health')
def health():
    return {'status': 'ok', 'version': 'v5'}, 200

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

# ─── SEED ────────────────────────────────────────────────────
def seed():
    db.create_all()
    if Section.query.first(): return

    secs = {}
    for nm in ['Section A', 'Section B', 'Section C', 'Section D']:
        s = Section(name=nm); db.session.add(s); db.session.flush(); secs[nm] = s.id

    def U(uid, nar, nen, role, sec, pwd, rec, bio=''):
        db.session.add(User(uid=uid, pwd_hash=generate_password_hash(pwd),
            name_ar=nar, name_en=nen, role=role,
            section_id=secs.get(sec), bio=bio, recovery_code=rec, active=True))

    U('YASSER_DEV','ياسر محمد مظلوم','Yasser Mohammed','مطور',None,'dev@uniportal2025','00000','مطور النظام')
    U('HEAD001','أ.د. كريم الجبوري','Prof. Kareem','رئيس',None,'1234','11111','رئيس القسم')
    U('COORD001','د. منى الكاظمي','Dr. Mona','مقرر',None,'1234','22222','مقرر القسم')
    U('DOC001','د. علي الحسيني','Dr. Ali','دكتور','Section A','1234','33333','Microbiology')
    U('DOC002','د. سارة النجار','Dr. Sara','دكتور','Section B','1234','44444','Cell Biology')
    U('DOC003','د. حسن المعموري','Dr. Hassan','دكتور','Section C','1234','55555','Ecology')
    U('REP001','محمد الزبيدي','Mohammed','ممثل','Section A','1234','66666','ممثل شعبة A')
    U('REP002','نور الهاشمي','Noor','ممثل','Section B','1234','77777','ممثل شعبة B')
    db.session.flush()

    try:
        from students_data import STUDENTS
        for exam_id, name_ar, pwd, recovery in STUDENTS:
            db.session.add(User(uid=exam_id, pwd_hash=generate_password_hash(pwd),
                name_ar=name_ar, name_en=name_ar, role='طالب',
                section_id=secs.get('Section A'),
                bio='طالب – قسم علوم الحياة', recovery_code=recovery, active=True))
        db.session.flush()
        print(f'✅ {len(STUDENTS)} students added')
    except Exception as e:
        print(f'Students: {e}')

    def uid2id(uid):
        u = User.query.filter_by(uid=uid).first(); return u.id if u else None

    chs = [
        ('uni_ann','ann','📢 الإعلانات الجامعية','University Announcements',
         'إعلانات رئيس القسم','HEAD001',None,'📢','#fbbf24'),
        ('gen','ann','📣 التبليغات العامة','General Announcements',
         'تبليغات عامة لجميع الأعضاء','COORD001',None,'📣','#ef4444'),
        ('dm1','doc','🦠 الأحياء الدقيقة','Microbiology',
         'محاضرات Microbiology – د.علي','DOC001','Section A','🦠','#00d4ff'),
        ('dm2','doc','🧬 الوراثة الجزيئية','Molecular Genetics',
         'Molecular Genetics – د.علي','DOC001','Section A','🧬','#22c55e'),
        ('dm3','doc','🔬 بيولوجيا الخلية','Cell Biology',
         'Cell Biology – د.سارة','DOC002','Section B','🔬','#a855f7'),
        ('dm4','doc','🌿 علم البيئة','Ecology',
         'Ecology – د.حسن','DOC003','Section C','🌿','#f59e0b'),
        ('rp1','rep','📣 إعلانات شعبة A','Section A News',
         'ممثل شعبة A','REP001','Section A','📣','#a855f7'),
        ('rp2','rep','📣 إعلانات شعبة B','Section B News',
         'ممثل شعبة B','REP002','Section B','📣','#a855f7'),
    ]
    ch_objs = {}
    for ck, ct, nar, nen, dar, own, sec, icon, color in chs:
        ch = Channel(ch_key=ck, ch_type=ct, name_ar=nar, name_en=nen,
                     desc_ar=dar, desc_en=dar, owner_id=uid2id(own),
                     section_id=secs.get(sec), icon=icon, color=color)
        db.session.add(ch); db.session.flush(); ch_objs[ck] = ch

    def M(ck, uid, mt, text=None, fname=None, url=None):
        db.session.add(Message(channel_id=ch_objs[ck].id, sender_id=uid2id(uid),
                               msg_type=mt, text=text, file_name=fname, link_url=url))

    M('gen','COORD001','txt','مرحباً بجميع أعضاء قسم علوم الحياة في UniPortal 🎉')
    M('dm1','DOC001','txt','🦠 قناة الأحياء الدقيقة\nسأنشر هنا المحاضرات والملفات')
    M('dm1','DOC001','pdf',fname='Microbiology_Ch7_Biofilm.pdf')
    M('dm2','DOC001','txt','🧬 قناة الوراثة الجزيئية')
    M('dm2','DOC001','pdf',fname='Genetics_L4_CRISPR.pdf')
    M('dm3','DOC002','txt','🔬 بيولوجيا الخلية – د.سارة النجار')
    M('dm4','DOC003','txt','🌿 علم البيئة – د.حسن المعموري')
    M('rp1','REP001','txt','📣 أهلاً بطلاب شعبة A!')
    M('rp2','REP002','txt','📣 قناة إعلانات شعبة B')

    anns_data = [
        ('HEAD001','🎉 أهلاً بكم في UniPortal',
         'مرحباً بجميع أعضاء قسم علوم الحياة في المنصة الرسمية لجامعة التراث.',True,'🎉','#0066cc',412),
        ('COORD001','📅 جدول الامتحانات النهائية',
         'تم إصدار جدول الامتحانات النهائية للفصل الثاني.',True,'📅','#ef4444',380),
        ('COORD001','⚠️ آخر موعد لتسديد الرسوم',
         'آخر موعد: 30 أبريل 2026. مراجعة الدائرة المالية.',False,'⚠️','#f59e0b',195),
    ]
    for ow, tar, car, pin, emoji, color, views in anns_data:
        db.session.add(Announcement(author_id=uid2id(ow), title_ar=tar, title_en=tar,
                                    content_ar=car, content_en=car, pinned=pin,
                                    emoji=emoji, color=color, views=views))
    db.session.commit()
    print(f'✅ Seeded: {User.query.count()} users, {Channel.query.count()} channels')

# ─── INIT ────────────────────────────────────────────────────
with app.app_context():
    try: os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    except: pass
    try: seed()
    except Exception as e:
        print(f'Seed error: {e}')
        import traceback; traceback.print_exc()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)


# ─── DEVELOPER: ADD USER ────────────────────────────────────────────────
@app.route('/api/dev/add-user', methods=['POST'])
@auth_required
def api_dev_add_user():
    u = cu()
    if u.role != 'مطور':
        return jsonify({'error': 'forbidden'}), 403
    d   = request.get_json() or {}
    uid = d.get('uid','').strip().upper()
    if not uid or User.query.filter_by(uid=uid).first():
        return jsonify({'ok': False, 'error': 'الرقم موجود مسبقاً أو فارغ'})
    role = d.get('role','طالب')
    if role not in ROLES: role = 'طالب'
    new_u = User(
        uid         = uid,
        pwd_hash    = generate_password_hash(d.get('password','1234')),
        name_ar     = d.get('name_ar', uid),
        name_en     = d.get('name_en', uid),
        role        = role,
        section_id  = d.get('section_id') or None,
        bio         = d.get('bio',''),
        recovery_code = d.get('recovery_code','00000'),
        active      = True
    )
    db.session.add(new_u); db.session.commit()
    return jsonify({'ok': True, 'user': new_u.to_dict()})

@app.route('/api/dev/reset-password', methods=['POST'])
@auth_required
def api_dev_reset_pwd():
    u  = cu()
    if u.role != 'مطور': return jsonify({'error': 'forbidden'}), 403
    d  = request.get_json() or {}
    target = User.query.filter_by(uid=d.get('uid','').upper()).first()
    if not target: return jsonify({'ok': False, 'error': 'المستخدم غير موجود'})
    target.pwd_hash = generate_password_hash(d.get('password','1234'))
    db.session.commit()
    return jsonify({'ok': True})

# ─── DIRECT MESSAGES ─────────────────────────────────────────────────────
@app.route('/api/dm/<string:target_uid>')
@auth_required
def api_get_dm(target_uid):
    me     = cu()
    target = User.query.filter_by(uid=target_uid.upper(), active=True).first()
    if not target: return jsonify({'error': 'user not found'}), 404
    # Create or find DM channel
    ids = sorted([me.id, target.id])
    dm_key = f'dm_{ids[0]}_{ids[1]}'
    ch = Channel.query.filter_by(ch_key=dm_key).first()
    if not ch:
        ch = Channel(ch_key=dm_key, ch_type='dm',
                     name_ar=target.name_ar, name_en=target.name_en or target.name_ar,
                     desc_ar='محادثة خاصة', desc_en='Direct Message',
                     owner_id=me.id, section_id=None,
                     icon='💬', color='#00d4ff')
        db.session.add(ch); db.session.flush()
        db.session.add(Message(channel_id=ch.id, msg_type='sys',
                               text=f'بدأت محادثة مع {target.name_ar}'))
        db.session.commit()
    pg   = request.args.get('page', 1, type=int)
    msgs = ch.messages.order_by(Message.created_at.asc()).paginate(page=pg, per_page=80)
    return jsonify({
        'channel': ch.to_dict(),
        'messages': [m.to_dict() for m in msgs.items],
        'partner': target.to_dict()
    })

@app.route('/api/dm/<string:target_uid>', methods=['POST'])
@auth_required
def api_send_dm(target_uid):
    me     = cu()
    target = User.query.filter_by(uid=target_uid.upper(), active=True).first()
    if not target: return jsonify({'error': 'user not found'}), 404
    ids    = sorted([me.id, target.id])
    dm_key = f'dm_{ids[0]}_{ids[1]}'
    ch     = Channel.query.filter_by(ch_key=dm_key).first()
    if not ch: return jsonify({'error': 'open DM first'}), 400
    text = request.form.get('text','').strip()
    file = request.files.get('file')
    mt   = 'txt'; fp = fn = None
    if file and file.filename and allowed_file(file.filename):
        ext   = file.filename.rsplit('.',1)[1].lower()
        fname = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secure_filename(file.filename)}"
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
        fp = f"/uploads/{fname}"; fn = file.filename
        mt = 'pdf' if ext=='pdf' else 'img'
    elif not text: return jsonify({'error':'empty'}),400
    msg = Message(channel_id=ch.id, sender_id=me.id, msg_type=mt,
                  text=text or None, file_path=fp, file_name=fn)
    db.session.add(msg); db.session.commit()
    # Notify target
    db.session.add(Notif(user_id=target.id,
        title_ar=f'رسالة خاصة من {me.name_ar}',
        body_ar=text[:60] if text else (fn or '📎'),
        ch_key=dm_key))
    push_to_user(target.id, f'رسالة خاصة من {me.name_ar}', text[:60] if text else '📎')
    db.session.commit()
    return jsonify({'ok': True, 'message': msg.to_dict()})

@app.route('/api/dm-list')
@auth_required
def api_dm_list():
    me = cu()
    # Find all DM channels where user is involved
    all_chs = Channel.query.filter_by(ch_type='dm').all()
    result  = []
    for ch in all_chs:
        if not ch.ch_key.startswith('dm_'): continue
        parts = ch.ch_key.replace('dm_','').split('_')
        if len(parts) != 2: continue
        if str(me.id) not in parts: continue
        partner_id = int(parts[0]) if str(me.id)==parts[1] else int(parts[1])
        partner    = User.query.get(partner_id)
        if not partner: continue
        last = ch.messages.order_by(Message.created_at.desc()).first()
        result.append({
            'ch_key': ch.ch_key,
            'partner': partner.to_dict(),
            'last_msg': (last.text or '')[:50] if last else '',
            'last_time': last.created_at.strftime('%Y-%m-%dT%H:%M:%S') if last else None,
        })
    return jsonify(result)

@app.route('/api/search-users')
@auth_required
def api_search_users():
    q = request.args.get('q','').strip()
    if len(q) < 2: return jsonify([])
    users = User.query.filter(
        (User.name_ar.ilike(f'%{q}%') | User.uid.ilike(f'%{q}%')),
        User.active == True,
        User.id != cu().id
    ).limit(10).all()
    return jsonify([u.to_dict() for u in users])


# ─── ROOMS (Discord-style) ───────────────────────────────────────────────
@app.route('/api/rooms', methods=['GET'])
@auth_required
def api_get_rooms():
    u   = cu()
    # Rooms visible to user based on role permissions
    chs = Channel.query.filter_by(ch_type='room').all()
    rd  = ROLES.get(u.role, ROLES['طالب'])
    out = []
    for ch in chs:
        import json as jsonlib
        perms = jsonlib.loads(ch.desc_en or '{}') if ch.desc_en and ch.desc_en.startswith('{') else {}
        allowed_roles = perms.get('roles', ['مطور','رئيس','مقرر','ممثل','دكتور','طالب'])
        if u.role in allowed_roles or ch.owner_id == u.id:
            d2 = ch.to_dict()
            last = ch.messages.order_by(Message.created_at.desc()).first()
            d2['last_msg']  = (last.text or '')[:50] if last else ''
            d2['last_time'] = last.created_at.strftime('%Y-%m-%dT%H:%M:%S') if last else None
            d2['can_write'] = u.role in perms.get('write_roles', allowed_roles) or ch.owner_id == u.id
            d2['perms']     = perms
            out.append(d2)
    return jsonify(out)

@app.route('/api/rooms', methods=['POST'])
@auth_required
def api_create_room():
    u = cu()
    if u.role != 'مطور':
        return jsonify({'error': 'only developer can create rooms'}), 403
    import json as jsonlib, time as t2
    d    = request.get_json() or {}
    name = d.get('name_ar','غرفة جديدة')[:120]
    icon = d.get('icon','🏠')
    color= d.get('color','#0066cc')
    read_roles  = d.get('read_roles',  ['مطور','رئيس','مقرر','ممثل','دكتور','طالب'])
    write_roles = d.get('write_roles', ['مطور','رئيس','مقرر','ممثل','دكتور'])
    perms = {'roles': read_roles, 'write_roles': write_roles}
    ch = Channel(
        ch_key     = f'room_{u.id}_{int(t2.time())}',
        name_ar    = f'{icon} {name}',
        name_en    = f'{icon} {name}',
        desc_ar    = d.get('desc_ar','غرفة عامة'),
        desc_en    = jsonlib.dumps(perms),
        ch_type    = 'room',
        owner_id   = u.id,
        section_id = None,
        icon       = icon,
        color      = color
    )
    db.session.add(ch); db.session.flush()
    db.session.add(Message(channel_id=ch.id, msg_type='sys',
                           text=f'🏠 تم إنشاء الغرفة بواسطة {u.name_ar}'))
    db.session.commit()
    return jsonify({'ok': True, 'room': ch.to_dict()})

@app.route('/api/rooms/<string:ck>/messages')
@auth_required
def api_room_msgs(ck):
    u  = cu()
    ch = Channel.query.filter_by(ch_key=ck, ch_type='room').first_or_404()
    pg   = request.args.get('page', 1, type=int)
    msgs = ch.messages.order_by(Message.created_at.asc()).paginate(page=pg, per_page=80)
    return jsonify({'messages': [m.to_dict() for m in msgs.items]})

@app.route('/api/rooms/<string:ck>/messages', methods=['POST'])
@auth_required
def api_send_room_msg(ck):
    u  = cu()
    ch = Channel.query.filter_by(ch_key=ck, ch_type='room').first_or_404()
    import json as jsonlib
    perms = jsonlib.loads(ch.desc_en or '{}') if ch.desc_en and ch.desc_en.startswith('{') else {}
    write_roles = perms.get('write_roles', list(ROLES.keys()))
    if u.role not in write_roles and ch.owner_id != u.id:
        return jsonify({'error': 'forbidden'}), 403
    text = request.form.get('text','').strip()
    if not text: return jsonify({'error':'empty'}),400
    msg = Message(channel_id=ch.id, sender_id=u.id, msg_type='txt', text=text)
    db.session.add(msg); db.session.commit()
    return jsonify({'ok': True, 'message': msg.to_dict()})

# ─── INSTAGRAM-STYLE POSTS ───────────────────────────────────────────────
class Post(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    author_id  = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    caption    = db.Column(db.Text)
    image_path = db.Column(db.String(400))
    likes      = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    author     = db.relationship('User', backref='posts')

    def to_dict(self):
        return {'id':self.id,'author_id':self.author_id,
                'author_name':self.author.name_ar if self.author else None,
                'author_photo':self.author.photo_url if self.author else None,
                'author_role':self.author.role if self.author else None,
                'caption':self.caption,'image_path':self.image_path,
                'likes':self.likes,'created_at':self.created_at.strftime('%Y-%m-%dT%H:%M:%S')}

@app.route('/api/posts')
@auth_required
def api_posts():
    posts = Post.query.order_by(Post.created_at.desc()).limit(30).all()
    return jsonify([p.to_dict() for p in posts])

@app.route('/api/posts', methods=['POST'])
@auth_required
def api_create_post():
    u    = cu()
    cap  = request.form.get('caption','').strip()
    file = request.files.get('image')
    ip   = None
    if file and allowed_file(file.filename):
        ext = file.filename.rsplit('.',1)[1].lower()
        fn  = f"post_{u.id}_{int(datetime.now().timestamp())}.{ext}"
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], fn))
        ip = f"/uploads/{fn}"
    if not cap and not ip:
        return jsonify({'error': 'empty'}), 400
    post = Post(author_id=u.id, caption=cap, image_path=ip)
    db.session.add(post); db.session.commit()
    return jsonify({'ok': True, 'post': post.to_dict()})

@app.route('/api/posts/<int:pid>/like', methods=['POST'])
@auth_required
def api_like_post(pid):
    post = Post.query.get_or_404(pid)
    post.likes += 1
    db.session.commit()
    return jsonify({'ok': True, 'likes': post.likes})

@app.route('/api/posts/<int:pid>', methods=['DELETE'])
@auth_required
def api_del_post(pid):
    u    = cu()
    post = Post.query.get_or_404(pid)
    if post.author_id != u.id and not ROLES.get(u.role,{}).get('admin'):
        return jsonify({'error':'forbidden'}),403
    db.session.delete(post); db.session.commit()
    return jsonify({'ok': True})
