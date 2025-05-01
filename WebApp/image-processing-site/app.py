from flask import Flask, render_template, request, send_file, redirect, url_for, flash
from flask_wtf.csrf import CSRFProtect
from werkzeug.utils import secure_filename
from pathlib import Path
from PIL import Image
from processor import process_images, resize_image
import cv2
import io
import zipfile
import logging
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', os.urandom(24).hex())

# Enable CSRF protection
csrf = CSRFProtect(app)

# Configuration
UPLOAD_DIR = Path('uploads')
PROCESSED_DIR = Path('processed')
ALLOWED_IMAGE_EXTS = {'jpg', 'jpeg', 'png', 'webp', 'heic'}
ALLOWED_VIDEO_EXTS = {'mp4', 'avi', 'mov', 'mkv'}
MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB

# Create directories
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def allowed_image_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTS

def allowed_video_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_VIDEO_EXTS

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'GET':
        return render_template('upload.html')

    if 'images' not in request.files:
        flash('No files selected', 'error')
        return redirect(url_for('upload'))

    try:
        files = request.files.getlist('images')
        temp_paths = []
        output_paths = []

        # Validate and save files
        for file in files:
            if file.filename.strip() == '':
                continue

            filename = secure_filename(file.filename)
            if not allowed_image_file(filename):
                app.logger.warning(f"Rejected invalid file: {filename}")
                continue

            temp_path = UPLOAD_DIR / filename
            file.save(temp_path)
            temp_paths.append(temp_path)

        if not temp_paths:
            flash('No valid images uploaded', 'error')
            return redirect(url_for('upload'))

        # Process images
        processed_files = process_images(temp_paths, PROCESSED_DIR)
        output_paths = [Path(p) for p in processed_files]

        if not output_paths:
            flash('No images could be processed', 'error')
            return redirect(url_for('upload'))

        # Create ZIP
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file_path in output_paths:
                zipf.write(file_path, arcname=file_path.name)

        zip_buffer.seek(0)

        # Cleanup
        for path in temp_paths + output_paths:
            try:
                if path.exists():
                    path.unlink()
            except Exception as e:
                app.logger.error(f"Cleanup error: {str(e)}")

        return send_file(
            zip_buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name='converted_images.zip'
        )

    except Exception as e:
        app.logger.error(f"Upload error: {str(e)}", exc_info=True)
        flash('An error occurred during processing', 'error')
        return redirect(url_for('upload'))

@app.route('/resize', methods=['GET', 'POST'])
def resize():
    if request.method == 'GET':
        return render_template('resize.html')

    try:
        if 'image' not in request.files:
            flash('No image selected', 'error')
            return redirect(url_for('resize'))

        file = request.files['image']
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(url_for('resize'))

        width = request.form.get('width', type=int)
        height = request.form.get('height', type=int)
        fmt = request.form.get('format', 'jpg').lower()

        if not (width and height):
            flash('Please provide valid dimensions', 'error')
            return redirect(url_for('resize'))

        filename = secure_filename(file.filename)
        if not allowed_image_file(filename):
            flash('Invalid image format', 'error')
            return redirect(url_for('resize'))

        temp_path = UPLOAD_DIR / filename
        file.save(temp_path)

        # Convert HEIC to JPEG first if needed
        if temp_path.suffix.lower() == '.heic':
            heic_path = temp_path
            temp_path = temp_path.with_suffix('.jpg')
            with Image.open(heic_path) as img:
                img.convert('RGB').save(temp_path)
            heic_path.unlink()

        output_filename = f"resized_{temp_path.stem}.{fmt}"
        output_path = PROCESSED_DIR / output_filename
        resize_image(temp_path, output_path, width, height, fmt.upper())

        # Cleanup
        if temp_path.exists():
            temp_path.unlink()

        return send_file(
            output_path,
            as_attachment=True,
            download_name=output_filename,
            mimetype=f'image/{fmt}'
        )

    except Exception as e:
        app.logger.error(f"Resize error: {str(e)}", exc_info=True)
        flash(f'Error processing image: {str(e)}', 'error')
        return redirect(url_for('resize'))

@app.route('/video', methods=['GET', 'POST'])
def video():
    if request.method == 'GET':
        return render_template('video.html')

    try:
        if 'video' not in request.files:
            flash('No video selected', 'error')
            return redirect(url_for('video'))

        file = request.files['video']
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(url_for('video'))

        fps = request.form.get('fps', 1, type=int)
        filename = secure_filename(file.filename)
        
        if not allowed_video_file(filename):
            flash('Invalid video format', 'error')
            return redirect(url_for('video'))

        temp_path = UPLOAD_DIR / filename
        file.save(temp_path)

        cap = cv2.VideoCapture(str(temp_path))
        if not cap.isOpened():
            raise ValueError("Could not open video file")

        frame_count = 0
        output_paths = []
        success = True

        while success:
            success, frame = cap.read()
            if not success:
                break

            if frame_count % fps == 0:
                output_path = PROCESSED_DIR / f"frame_{frame_count:04d}.jpg"
                if cv2.imwrite(str(output_path), frame):
                    output_paths.append(output_path)
                else:
                    app.logger.error(f"Failed to save frame {frame_count}")

            frame_count += 1

        cap.release()

        if not output_paths:
            flash('No frames extracted from video', 'error')
            return redirect(url_for('video'))

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for path in output_paths:
                zipf.write(path, path.name)

        zip_buffer.seek(0)

        # Cleanup
        if temp_path.exists():
            temp_path.unlink()
        for path in output_paths:
            if path.exists():
                path.unlink()

        return send_file(
            zip_buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name='video_frames.zip'
        )

    except Exception as e:
        app.logger.error(f"Video error: {str(e)}", exc_info=True)
        flash(f'Error processing video: {str(e)}', 'error')
        return redirect(url_for('video'))

if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    )