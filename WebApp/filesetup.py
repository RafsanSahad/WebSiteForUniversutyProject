import os

# Define folder structure
project_name = "image-processing-site"
folders = [
    f"{project_name}/static/uploads",
    f"{project_name}/templates"
]

# Create folders
for folder in folders:
    os.makedirs(folder, exist_ok=True)

# Create app.py with placeholder code
app_py_content = '''from flask import Flask, render_template, request, send_file
from PIL import Image
import os

app = Flask(__name__)
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_image():
    if 'image' not in request.files:
        return 'No image uploaded!', 400

    file = request.files['image']
    path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
    file.save(path)

    # Example: Convert to grayscale
    img = Image.open(path).convert('L')
    output_path = os.path.join(app.config['UPLOAD_FOLDER'], 'processed_' + file.filename)
    img.save(output_path)

    return send_file(output_path, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
'''

with open(f"{project_name}/app.py", "w") as f:
    f.write(app_py_content)

# Create index.html
index_html = '''<!DOCTYPE html>
<html>
<head>
    <title>Image Processor</title>
</head>
<body>
    <h1>Upload Image</h1>
    <form action="/upload" method="post" enctype="multipart/form-data">
        <input type="file" name="image" required>
        <button type="submit">Upload & Process</button>
    </form>
</body>
</html>
'''

with open(f"{project_name}/templates/index.html", "w") as f:
    f.write(index_html)

# Create requirements.txt
requirements = "flask\npillow\n"
with open(f"{project_name}/requirements.txt", "w") as f:
    f.write(requirements)

print(f"✅ Project '{project_name}' structure created successfully.")
