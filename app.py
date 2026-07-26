import os
import json
from flask import Flask, request, jsonify, render_template, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='static', template_folder='templates')
BG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bg')
THEMES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'themes.json')

os.makedirs(BG_DIR, exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/bg/<path:filename>')
def serve_bg(filename):
    return send_from_directory(BG_DIR, filename)

@app.route('/publish', methods=['POST'])
def publish():
    try:
        # Get theme name to generate filenames
        theme_name = request.form.get('name', 'default_theme')
        # sanitize name for filename
        safe_name = "".join([c for c in theme_name if c.isalpha() or c.isdigit() or c==' ']).rstrip().replace(" ", "_").lower()
        if not safe_name:
            safe_name = "theme"
            
        bg_file = request.files.get('backgroundFile')
        prew_file = request.files.get('previewFile')
        
        bg_filename = f"{safe_name}_bg.jpg"
        prew_filename = f"{safe_name}_bg_prew.jpg"
        
        if bg_file:
            bg_file.save(os.path.join(BG_DIR, bg_filename))
        if prew_file:
            prew_file.save(os.path.join(BG_DIR, prew_filename))
            
        # Construct theme object
        new_theme = {
            "name": theme_name,
            "backgroundUrl": f"https://mobile-version.feast.tr/bg/{bg_filename}",
            "previewUrl": f"https://mobile-version.feast.tr/bg/{prew_filename}",
            "sentBubbleColor": request.form.get('sentBubbleColor', '#FF3131'),
            "receivedBubbleColor": request.form.get('receivedBubbleColor', '#FFFFFF'),
            "sentTextColor": request.form.get('sentTextColor', '#FFFFFF'),
            "receivedTextColor": request.form.get('receivedTextColor', '#000000'),
            "appBarColor": request.form.get('appBarColor', '#1E1E28'),
            "appBarTextColor": request.form.get('appBarTextColor', '#FFFFFF'),
            "inputBoxColor": request.form.get('inputBoxColor', '#FFFFFF'),
            "inputTextColor": request.form.get('inputTextColor', '#000000'),
            "sendButtonColor": request.form.get('sendButtonColor', '#FF3131')
        }
        
        # Update JSON
        themes = []
        if os.path.exists(THEMES_FILE):
            with open(THEMES_FILE, 'r', encoding='utf-8') as f:
                try:
                    themes = json.load(f)
                except json.JSONDecodeError:
                    themes = []
                    
        themes.append(new_theme)
        
        with open(THEMES_FILE, 'w', encoding='utf-8') as f:
            json.dump(themes, f, indent=2, ensure_ascii=False)
            
        return jsonify({"success": True, "theme": new_theme})
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
