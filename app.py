import os
import re
import json
import hashlib
import subprocess
from flask import Flask, request, jsonify, render_template, send_from_directory

app = Flask(__name__, static_folder='static', template_folder='templates')
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
BG_DIR = os.path.join(PROJECT_DIR, 'bg')
THEMES_FILE = os.path.join(PROJECT_DIR, 'themes.json')
PUBLIC_BG_URL = 'https://mobile-version.feast.tr/bg/'

# Every colour of a theme, in the order themes.json lists them, with the value
# a form from an older builder page falls back to.
COLOR_FIELDS = {
    'sentBubbleColor': '#FF3131',
    'receivedBubbleColor': '#FFFFFF',
    'sentTextColor': '#FFFFFF',
    'receivedTextColor': '#000000',
    'appBarColor': '#1E1E28',
    'appBarTextColor': '#FFFFFF',
    'inputBoxColor': '#FFFFFF',
    'inputTextColor': '#000000',
    'sendButtonColor': '#FF3131',
    # The chat's own centred lines ("X sohbet temasını Y olarak değiştirdi",
    # "X gruba katıldı") are drawn straight on the background picture, so
    # this is the one colour picked against the picture itself.
    'systemTextColor': '#000000',
}
# The app drops a theme whose colour it cannot parse from the list without a
# word, so only plain #RRGGBB goes out.
HEX_COLOR = re.compile(r'^#[0-9a-fA-F]{6}$')
TURKISH_TO_ASCII = str.maketrans('çğıöşüâîûÇĞİÖŞÜÂÎÛ', 'cgiosuaiuCGIOSUAIU')

os.makedirs(BG_DIR, exist_ok=True)


class ThemeError(ValueError):
    """A theme the app could not use; the message is shown to the designer."""


def load_themes():
    if not os.path.exists(THEMES_FILE):
        return []

    with open(THEMES_FILE, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def save_themes(themes):
    with open(THEMES_FILE, 'w', encoding='utf-8') as f:
        json.dump(themes, f, indent=2, ensure_ascii=False)


def theme_name_exists(themes, theme_name, ignore_index=None):
    normalized_name = theme_name.strip().casefold()
    return any(
        index != ignore_index and theme.get('name', '').strip().casefold() == normalized_name
        for index, theme in enumerate(themes)
    )


def run_git_command(*args):
    """Run a Git command in this project's repository and return its output."""
    result = subprocess.run(
        ['git', '-c', f'safe.directory={PROJECT_DIR}', *args],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return result.stdout.strip()


def commit_and_push(commit_message):
    run_git_command('add', '--all')
    run_git_command('commit', '-m', commit_message)
    run_git_command('push')


def sync_repository():
    """Bring the local repository up to date before making a theme change."""
    return run_git_command('pull', '--rebase')


def git_error_response(error):
    if isinstance(error, subprocess.CalledProcessError):
        command = ' '.join(error.cmd)
        details = (error.stderr or error.stdout or 'Bilinmeyen Git hatası').strip()
        message = f"Git komutu başarısız oldu ({command}): {details}"
    else:
        message = "Git işlemi zaman aşımına uğradı."
    return jsonify({"success": False, "error": message}), 500


def file_slug(theme_name):
    """ASCII file-name stem for a theme: 'Şeker Tadı' -> 'seker_tadi'."""
    ascii_name = theme_name.translate(TURKISH_TO_ASCII).lower()
    return re.sub(r'[^a-z0-9]+', '_', ascii_name).strip('_') or 'theme'


def read_image(upload):
    """The uploaded picture's bytes and extension; only what the app decodes."""
    data = upload.read()
    if data.startswith(b'\xff\xd8\xff'):
        return data, 'jpg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return data, 'png'
    raise ThemeError('Görsel JPEG ya da PNG olmalı.')


def save_image(data, extension, slug, kind):
    """Store a picture under a name taken from its content; returns its URL.

    The app downloads a background once per URL and keeps it for good
    (ChatThemeSync.downloadBackground), and the theme grid caches previews by
    URL too, so a new picture written over an old file name would never reach
    a phone that already has the old one. A different picture therefore gets
    a different name. The old file stays: chats that picked the theme earlier
    still send its URL to the other side.
    """
    digest = hashlib.sha1(data).hexdigest()[:10]
    filename = f'{slug}_{kind}_{digest}.{extension}'
    with open(os.path.join(BG_DIR, filename), 'wb') as f:
        f.write(data)
    return PUBLIC_BG_URL + filename


def build_theme(form, files, existing_theme=None):
    """The theme a form describes; raises ThemeError before writing anything."""
    existing = existing_theme or {}
    theme_name = form.get('name', '').strip()
    if not theme_name:
        raise ThemeError('Tema adı boş olamaz.')

    colors = {}
    for field, fallback in COLOR_FIELDS.items():
        # A form from an older builder page leaves an edited theme's value as
        # it was.
        value = (form.get(field) or existing.get(field) or fallback).strip()
        if not HEX_COLOR.match(value):
            raise ThemeError(f'Geçersiz renk ({field}): {value}')
        colors[field] = value

    bg_file = files.get('backgroundFile')
    preview_file = files.get('previewFile')
    background = read_image(bg_file) if bg_file else None
    preview = read_image(preview_file) if preview_file else None
    if not background and not existing.get('backgroundUrl'):
        # The app downloads the picture before it applies a theme and gives up
        # when that fails, so a theme without one could never be picked.
        raise ThemeError('Arka plan görseli seçilmedi.')

    slug = file_slug(theme_name)
    background_url = (
        save_image(*background, slug, 'bg') if background
        else existing['backgroundUrl']
    )
    preview_url = (
        save_image(*preview, slug, 'bg_prew') if preview
        else existing.get('previewUrl') or background_url
    )
    return {
        'name': theme_name,
        'backgroundUrl': background_url,
        'previewUrl': preview_url,
        **colors,
    }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/bg/<path:filename>')
def serve_bg(filename):
    return send_from_directory(BG_DIR, filename)


@app.route('/api/themes', methods=['GET'])
def get_themes():
    return jsonify({"success": True, "themes": load_themes()})

@app.route('/publish', methods=['POST'])
def publish():
    try:
        # Pull before reading or writing themes so a new record is based on the
        # most recent version from other designers.
        try:
            sync_repository()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            return git_error_response(error)

        themes = load_themes()
        theme_name = request.form.get('name', '').strip()
        if theme_name_exists(themes, theme_name):
            return jsonify({"success": False, "error": "Bu adla kayıtlı bir tema zaten var."}), 409

        try:
            new_theme = build_theme(request.form, request.files)
        except ThemeError as error:
            return jsonify({"success": False, "error": str(error)}), 400
        themes.append(new_theme)
        save_themes(themes)

        commit_message = f"New Theme: {new_theme['name']}"
        try:
            commit_and_push(commit_message)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            return git_error_response(error)

        return jsonify({
            "success": True,
            "theme": new_theme,
            "index": len(themes) - 1,
            "commitMessage": commit_message,
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/themes/<int:theme_index>', methods=['PUT'])
def update_theme(theme_index):
    try:
        try:
            sync_repository()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            return git_error_response(error)

        themes = load_themes()
        if theme_index < 0 or theme_index >= len(themes):
            return jsonify({"success": False, "error": "Tema bulunamadı."}), 404

        theme_name = request.form.get('name', '').strip()
        if theme_name_exists(themes, theme_name, ignore_index=theme_index):
            return jsonify({"success": False, "error": "Bu adla kayıtlı bir tema zaten var."}), 409

        try:
            updated_theme = build_theme(request.form, request.files, themes[theme_index])
        except ThemeError as error:
            return jsonify({"success": False, "error": str(error)}), 400
        themes[theme_index] = updated_theme
        save_themes(themes)
        commit_message = f"Update Theme: {updated_theme['name']}"
        try:
            commit_and_push(commit_message)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            return git_error_response(error)

        return jsonify({"success": True, "theme": updated_theme, "commitMessage": commit_message})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/themes/<int:theme_index>', methods=['DELETE'])
def delete_theme(theme_index):
    try:
        try:
            sync_repository()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            return git_error_response(error)

        themes = load_themes()
        if theme_index < 0 or theme_index >= len(themes):
            return jsonify({"success": False, "error": "Tema bulunamadı."}), 404

        deleted_theme = themes.pop(theme_index)
        save_themes(themes)
        commit_message = f"Delete Theme: {deleted_theme['name']}"
        try:
            commit_and_push(commit_message)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            return git_error_response(error)

        return jsonify({"success": True, "commitMessage": commit_message})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    # Flask's debug reloader launches a child process. Pull only in the parent;
    # the child then starts from the repository that was just synchronized.
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        sync_repository()
    app.run(debug=True, port=5000)
