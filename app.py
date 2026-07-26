import os
import json
import subprocess
from flask import Flask, request, jsonify, render_template, send_from_directory

app = Flask(__name__, static_folder='static', template_folder='templates')
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
BG_DIR = os.path.join(PROJECT_DIR, 'bg')
THEMES_FILE = os.path.join(PROJECT_DIR, 'themes.json')

os.makedirs(BG_DIR, exist_ok=True)


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
        details = (error.stderr or error.stdout or 'Unknown Git error').strip()
        message = f"Git command failed ({command}): {details}"
    else:
        message = "Git operation timed out."
    return jsonify({"success": False, "error": message}), 500


def build_theme(form, files, existing_theme=None):
    theme_name = form.get('name', 'default_theme').strip() or 'default_theme'
    safe_name = ''.join(c for c in theme_name if c.isalnum() or c == ' ').rstrip().replace(' ', '_').lower() or 'theme'
    bg_file = files.get('backgroundFile')
    preview_file = files.get('previewFile')
    bg_filename = f'{safe_name}_bg.jpg'
    preview_filename = f'{safe_name}_bg_prew.jpg'

    if bg_file:
        bg_file.save(os.path.join(BG_DIR, bg_filename))
    if preview_file:
        preview_file.save(os.path.join(BG_DIR, preview_filename))

    theme = {
        'name': theme_name,
        'backgroundUrl': existing_theme.get('backgroundUrl') if existing_theme and not bg_file else f'https://mobile-version.feast.tr/bg/{bg_filename}',
        'previewUrl': (existing_theme.get('previewUrl') or existing_theme.get('backgroundUrl')) if existing_theme and not preview_file else f'https://mobile-version.feast.tr/bg/{preview_filename}',
        'sentBubbleColor': form.get('sentBubbleColor', '#FF3131'),
        'receivedBubbleColor': form.get('receivedBubbleColor', '#FFFFFF'),
        'sentTextColor': form.get('sentTextColor', '#FFFFFF'),
        'receivedTextColor': form.get('receivedTextColor', '#000000'),
        'appBarColor': form.get('appBarColor', '#1E1E28'),
        'appBarTextColor': form.get('appBarTextColor', '#FFFFFF'),
        'inputBoxColor': form.get('inputBoxColor', '#FFFFFF'),
        'inputTextColor': form.get('inputTextColor', '#000000'),
        'sendButtonColor': form.get('sendButtonColor', '#FF3131'),
    }
    return theme

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
        theme_name = request.form.get('name', '').strip() or 'default_theme'
        if theme_name_exists(themes, theme_name):
            return jsonify({"success": False, "error": "A theme with this name already exists."}), 409

        new_theme = build_theme(request.form, request.files)
        themes.append(new_theme)
        save_themes(themes)

        commit_message = f"New Theme: {new_theme['name']}"
        try:
            commit_and_push(commit_message)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            return git_error_response(error)

        return jsonify({"success": True, "theme": new_theme, "commitMessage": commit_message})
        
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
            return jsonify({"success": False, "error": "Theme not found."}), 404

        theme_name = request.form.get('name', '').strip() or 'default_theme'
        if theme_name_exists(themes, theme_name, ignore_index=theme_index):
            return jsonify({"success": False, "error": "A theme with this name already exists."}), 409

        updated_theme = build_theme(request.form, request.files, themes[theme_index])
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
            return jsonify({"success": False, "error": "Theme not found."}), 404

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
