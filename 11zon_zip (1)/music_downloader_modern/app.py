from flask import Flask, request, jsonify, render_template, send_file, redirect, url_for, flash, session, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from ytmusicapi import YTMusic
import os
import zipfile
import subprocess
from celery import Celery
import uuid
import yt_dlp
import io
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from flask_migrate import Migrate

app = Flask(__name__)
app.secret_key = 'your-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///music.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Celery config
app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'
celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)

ytmusic = YTMusic()
DOWNLOAD_DIR = "downloads"

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

def safe_filename(name):
    return "".join(c for c in name if c.isalnum() or c in " .-_").rstrip()

# --- Models ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    is_superuser = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class DownloadHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    filename = db.Column(db.String(200))
    timestamp = db.Column(db.DateTime, server_default=db.func.now())

# --- Auth ---
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('Username already exists')
            return redirect(url_for('register'))
        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful! Please log in.')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- Main Views ---
@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/search_playlist')
def search_playlist():
    name = request.args.get('name')
    results = ytmusic.search(name, filter='playlists')
    if not results:
        return jsonify({"songs": []})
    playlist_id = results[0]['browseId']
    playlist = ytmusic.get_playlist(playlist_id)
    songs = [{"title": t["title"], "videoId": t["videoId"]} for t in playlist['tracks']]
    return jsonify({"songs": songs})

@app.route('/download_all', methods=['POST'])
def download_all():
    data = request.json
    songs = data['songs']
    quality = data['quality']

    if os.path.exists(DOWNLOAD_DIR):
        for f in os.listdir(DOWNLOAD_DIR):
            os.remove(os.path.join(DOWNLOAD_DIR, f))
    else:
        os.makedirs(DOWNLOAD_DIR)

    for song in songs:
        url = f"https://www.youtube.com/watch?v={song['id']}"
        output_path = os.path.join(DOWNLOAD_DIR, f"{song['title']}.mp3")
        command = [
            "yt-dlp",
            "-x", "--audio-format", "mp3",
            "--audio-quality", quality,
            "-o", output_path,
            url
        ]
        result = subprocess.run(command, cwd=DOWNLOAD_DIR)

    zip_path = os.path.join(DOWNLOAD_DIR, "songs.zip")
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for f in os.listdir(DOWNLOAD_DIR):
            if f.endswith('.mp3'):
                zipf.write(os.path.join(DOWNLOAD_DIR, f), arcname=f)

    return send_file(zip_path, as_attachment=True, download_name='songs.zip')

@app.route('/progress/<task_id>')
@login_required
def progress(task_id):
    result = celery.AsyncResult(task_id)
    info = result.info if result.info else {}
    return jsonify({'state': result.state, 'progress': info.get('progress', 0), 'download_url': info.get('download_url')})

@app.route('/history')
@login_required
def history():
    downloads = DownloadHistory.query.filter_by(user_id=current_user.id).order_by(DownloadHistory.timestamp.desc()).all()
    return render_template('history.html', downloads=downloads)

@app.route('/download/<filename>')
@login_required
def download_file(filename):
    return send_file(
        os.path.join(DOWNLOAD_DIR, filename),
        as_attachment=True,
        download_name=filename  # Flask 2.x+
    )

@app.route('/download_all_history')
@login_required
def download_all_history():
    downloads = DownloadHistory.query.filter_by(user_id=current_user.id).all()
    filepaths = [os.path.join(DOWNLOAD_DIR, d.filename) for d in downloads if os.path.exists(os.path.join(DOWNLOAD_DIR, d.filename))]
    if not filepaths:
        return "No files to download.", 404
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w') as zipf:
        for filepath in filepaths:
            zipf.write(filepath, os.path.basename(filepath))
    zip_buffer.seek(0)
    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name='all_downloads.zip'
    )

def get_video_title(url):
    ydl_opts = {'quiet': True, 'skip_download': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return info.get('title', f"video_{uuid.uuid4()}")
    except Exception:
        return f"video_{uuid.uuid4()}"

@app.route('/download_video', methods=['POST'])
@login_required
def download_video():
    data = request.json
    url = data['url']
    format_code = data.get('format', 'bestvideo+bestaudio/best')
    merge_format = data.get('mergeFormat', 'mp4')
    title = get_video_title(url)
    safe_title = "".join(c for c in title if c.isalnum() or c in " .-_").rstrip()
    filename = f"{safe_title}.{merge_format}"
    output_path = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
    command = [
        "yt-dlp",
        "-f", format_code,
        "--merge-output-format", merge_format,
        "-o", output_path,
        url
    ]
    result = subprocess.run(command, cwd=DOWNLOAD_DIR)
    if result.returncode != 0:
        return jsonify({'error': 'Requested format is not available or YouTube is currently blocking some formats. Try a different quality or check for yt-dlp updates.'}), 500
    # Save to history
    user = db.session.get(User, current_user.id)
    if user:
        history = DownloadHistory(user_id=user.id, filename=filename)
        db.session.add(history)
        db.session.commit()
    return send_file(
        output_path,
        as_attachment=True,
        download_name=filename,
        mimetype=f'video/{merge_format}' if merge_format in ['mp4', 'webm'] else 'application/octet-stream'
    )

@app.route('/video_info', methods=['POST'])
@login_required
def video_info():
    data = request.json
    url = data['url']
    ydl_opts = {'quiet': True, 'skip_download': True, 'forcejson': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    print([f['ext'] for f in info.get('formats', [])])  # <-- Add this line
    formats = []
    for f in info.get('formats', []):
        if f.get('filesize') or f.get('filesize_approx'):
            size = f.get('filesize') or f.get('filesize_approx')
            size_mb = round(size / 1024 / 1024, 2)
        else:
            size_mb = None
        formats.append({
            'format_id': f['format_id'],
            'ext': f['ext'],
            'format_note': f.get('format_note', ''),
            'resolution': f.get('resolution', f"{f.get('width', '')}x{f.get('height', '')}"),
            'acodec': f.get('acodec', ''),
            'vcodec': f.get('vcodec', ''),
            'filesize_mb': size_mb,
            'abr': f.get('abr', ''),
            'asr': f.get('asr', ''),
            'audio_only': f.get('vcodec') == 'none' and f.get('acodec') != 'none',
            'video_only': f.get('acodec') == 'none' and f.get('vcodec') != 'none',
            'has_audio': f.get('acodec') != 'none',
        })
    return jsonify({
        'title': info.get('title'),
        'thumbnail': info.get('thumbnail'),
        'formats': formats
    })

@app.route('/download_mp3', methods=['POST'])
@login_required
def download_mp3():
    data = request.json
    url = data.get('url')
    quality = str(data.get('quality', '320'))
    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    # Get video title for filename
    ydl_opts = {'quiet': True, 'skip_download': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info.get('title', f"audio_{uuid.uuid4()}")

    filename = f"{safe_filename(title)}_{quality}kbps.mp3"
    output_path = os.path.join(DOWNLOAD_DIR, filename)

    # Download and convert to mp3
    command = [
        "yt-dlp",
        "-x", "--audio-format", "mp3",
        "--audio-quality", quality,
        "-o", output_path,
        url
    ]
    result = subprocess.run(command, cwd=DOWNLOAD_DIR)
    if result.returncode != 0:
        print(result.stderr)
        return jsonify({'error': 'yt-dlp failed', 'details': result.stderr}), 500

    if not os.path.exists(output_path):
        return jsonify({'error': 'Download failed'}), 500

    # Optionally save to history
    user = db.session.get(User, current_user.id)
    if user:
        history = DownloadHistory(user_id=user.id, filename=filename)
        db.session.add(history)
        db.session.commit()

    return send_file(output_path, as_attachment=True, download_name=filename)

@app.route('/download_instagram', methods=['POST'])
@login_required
def download_instagram():
    data = request.json
    url = data.get('url')
    quality = data.get('quality', 'best')
    if quality == 'best':
        format_str = 'bestvideo+bestaudio/best'
    else:
        quality_map = {
            '480': 'bestvideo[height<=480]+bestaudio/best[height<=480]',
            '720': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
            '1080': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]',
            '2k': 'bestvideo[height<=1440]+bestaudio/best[height<=1440]',
            '4k': 'bestvideo[height<=2160]+bestaudio/best[height<=2160]',
        }
        format_str = quality_map.get(quality, 'bestvideo+bestaudio/best')
    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    ydl_opts = {'quiet': True, 'skip_download': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info.get('title', f"insta_{uuid.uuid4()}")

    filename = f"{safe_filename(title)}_{quality}p.mp4"
    output_path = os.path.join(DOWNLOAD_DIR, filename)

    ydl_cmd = [
        "yt-dlp",
        "-f", format_str,
        "--merge-output-format", "mp4",
        "-o", output_path,
        url
    ]
    print(" ".join(f'"{arg}"' if ' ' in arg else arg for arg in ydl_cmd))  # Debug print

    result = subprocess.run(ydl_cmd, cwd=DOWNLOAD_DIR)
    if result.returncode != 0:
        print(result.stderr)
        return jsonify({'error': 'yt-dlp failed', 'details': result.stderr}), 500

    if not os.path.exists(output_path):
        return jsonify({'error': 'Download failed'}), 500

    return send_file(output_path, as_attachment=True, download_name=filename)

@app.route('/download_selected_format', methods=['POST'])
@login_required
def download_selected_format():
    data = request.get_json()
    url = data.get('url')
    format_string = data.get('formatString')
    merge_format = data.get('mergeFormat', 'mp4')

    if not url or not format_string or not merge_format:
        return jsonify({'error': 'Missing parameters'}), 400

    # Get video title for filename
    ydl_opts = {'quiet': True, 'skip_download': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', f"video_{uuid.uuid4()}")
    except Exception as e:
        return jsonify({'error': 'yt-dlp extract_info failed', 'details': str(e)}), 500

    filename = f"{safe_filename(title)}.{merge_format}"

    # Download the selected format and print the actual output file path
    command = [
        "yt-dlp",
        "-f", format_string,
        "--merge-output-format", merge_format,
        "-o", filename,
        url
    ]
    print("Running yt-dlp command:", " ".join(command))
    result = subprocess.run(command, cwd=DOWNLOAD_DIR)
    if result.returncode != 0:
        return jsonify({'error': 'Requested format is not available or YouTube is currently blocking some formats. Try a different quality or check for yt-dlp updates.'}), 500

    output_path = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(output_path):
        return jsonify({'error': 'Download failed'}), 500

    # Optionally save to history
    user = db.session.get(User, current_user.id)
    if user:
        history = DownloadHistory(user_id=user.id, filename=os.path.basename(output_path))
        db.session.add(history)
        db.session.commit()

    return send_file(output_path, as_attachment=True, download_name=filename)

# --- Celery Task ---
@celery.task(bind=True)
def download_songs_task(self, songs, quality, user_id, task_id):
    if os.path.exists(DOWNLOAD_DIR):
        for f in os.listdir(DOWNLOAD_DIR):
            os.remove(os.path.join(DOWNLOAD_DIR, f))
    else:
        os.makedirs(DOWNLOAD_DIR)
    total = len(songs)
    for i, song in enumerate(songs):
        url = f"https://www.youtube.com/watch?v={song['id']}"
        output_path = os.path.join(DOWNLOAD_DIR, f"{song['title']}.mp3")
        command = [
            "yt-dlp",
            "-x", "--audio-format", "mp3",
            "--audio-quality", quality,
            "-o", output_path,
            url
        ]
        result = subprocess.run(command, cwd=DOWNLOAD_DIR)
        self.update_state(state='PROGRESS', meta={'progress': int((i+1)/total*100)})
    zip_path = os.path.join(DOWNLOAD_DIR, f"songs_{task_id}.zip")
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for f in os.listdir(DOWNLOAD_DIR):
            if f.endswith('.mp3'):
                zipf.write(os.path.join(DOWNLOAD_DIR, f), arcname=f)
    # Save to history
    user = User.query.get(user_id)
    if user:
        history = DownloadHistory(user_id=user.id, filename=os.path.basename(zip_path))
        db.session.add(history)
        db.session.commit()
    return {'progress': 100, 'download_url': url_for('download_file', filename=os.path.basename(zip_path), _external=True)}

@celery.task(bind=True)
def download_video_task(self, url, quality, user_id, task_id):
    data = request.json
    self.update_state(state='PROGRESS', meta={'progress': 5})  # Indicate started
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
    output_path = os.path.join(DOWNLOAD_DIR, f"video_{task_id}.mp4")
    audio_quality = data.get('audioQuality', '320')
    command = [
        "yt-dlp",
        "-f", "bestvideo+bestaudio/best",  # always gets the best available (4K, 8K, etc.)
        "--merge-output-format", "mp4",
        "-o", output_path,
        "--audio-quality", audio_quality,
        url
    ]
    result = subprocess.run(command, cwd=DOWNLOAD_DIR)
    self.update_state(state='PROGRESS', meta={'progress': 90})  # Almost done
    # Save to history
    user = db.session.get(User, user_id)
    if user:
        history = DownloadHistory(user_id=user.id, filename=os.path.basename(output_path))
        db.session.add(history)
        db.session.commit()
    return {'progress': 100, 'download_url': url_for('download_file', filename=os.path.basename(output_path), _external=True)}

@celery.task(bind=True)
def download_mp3_task(self, url, quality, user_id, task_id):
    self.update_state(state='PROGRESS', meta={'progress': 5})
    ydl_opts = {'quiet': True, 'skip_download': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info.get('title', f"audio_{uuid.uuid4()}")
    filename = f"{safe_filename(title)}_{quality}kbps.mp3"
    output_path = os.path.join(DOWNLOAD_DIR, filename)
    command = [
        "yt-dlp",
        "-x", "--audio-format", "mp3",
        "--audio-quality", quality,
        "-o", output_path,
        url
    ]
    result = subprocess.run(command, cwd=DOWNLOAD_DIR)
    self.update_state(state='PROGRESS', meta={'progress': 90})
    # Save to history
    user = db.session.get(User, user_id)
    if user:
        history = DownloadHistory(user_id=user.id, filename=filename)
        db.session.add(history)
        db.session.commit()
    return {'progress': 100, 'download_url': url_for('download_file', filename=filename, _external=True)}

@celery.task(bind=True)
def download_instagram_task(self, url, quality, user_id, task_id):
    self.update_state(state='PROGRESS', meta={'progress': 5})
    quality_map = {
        '480': 'bestvideo[height<=480]+bestaudio/best[height<=480]',
        '720': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
        '1080': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]',
        '2k': 'bestvideo[height<=1440]+bestaudio/best[height<=1440]',
        '4k': 'bestvideo[height<=2160]+bestaudio/best[height<=2160]',
    }
    format_str = quality_map.get(quality, 'bestvideo+bestaudio/best')
    ydl_opts = {'quiet': True, 'skip_download': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info.get('title', f"insta_{uuid.uuid4()}")
    filename = f"{safe_filename(title)}_{quality}p.mp4"
    output_path = os.path.join(DOWNLOAD_DIR, filename)
    command = [
        "yt-dlp",
        "-f", format_str,
        "--merge-output-format", "mp4",
        "-o", output_path,
        url
    ]
    result = subprocess.run(command, cwd=DOWNLOAD_DIR)
    self.update_state(state='PROGRESS', meta={'progress': 90})
    # Save to history
    user = db.session.get(User, user_id)
    if user:
        history = DownloadHistory(user_id=user.id, filename=filename)
        db.session.add(history)
        db.session.commit()
    return {'progress': 100, 'download_url': url_for('download_file', filename=filename, _external=True)}

def superuser_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_superuser:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

@app.route('/admin')
@superuser_required
def admin_dashboard():
    users = User.query.all()
    downloads = DownloadHistory.query.order_by(DownloadHistory.timestamp.desc()).all()
    return render_template('admin.html', users=users, downloads=downloads)

@app.after_request
def add_header(response):
    if request.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'no-store'
    return response

migrate = Migrate(app, db)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)