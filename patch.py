with open('app.py', 'r') as f:
    content = f.read()

# Fix startup block
old = """with app.app_context():
    os.makedirs('uploads', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    seed_db()"""

new = """with app.app_context():
    try:
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    except Exception:
        pass
    try:
        os.makedirs('static', exist_ok=True)
    except Exception:
        pass
    seed_db()"""

content = content.replace(old, new)
with open('app.py', 'w') as f:
    f.write(content)
print("Done")
