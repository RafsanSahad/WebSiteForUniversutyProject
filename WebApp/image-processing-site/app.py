from flask import Flask, render_template, request, send_file, redirect, url_for, flash, abort
from flask_wtf.csrf import CSRFProtect, CSRFError
from werkzeug.utils import secure_filename
from pathlib import Path
from PIL import Image
from processor import process_images, resize_image, extract_frames, interpolate_frames, remove_background
import cv2
import io
import zipfile
import logging
import os
import uuid
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', os.urandom(24).hex())
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_CONTENT_LENGTH', 52428800))  # 50MB default
app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER', 'uploads')
app.config['FRAMES_FOLDER'] = os.getenv('FRAMES_FOLDER', 'frames')
app.config['PROCESSED_FOLDER'] = os.getenv('PROCESSED_FOLDER', 'processed')
app.config['WTF_CSRF_ENABLED'] = True  # Enable CSRF protection

# Enable CSRF protection
csrf = CSRFProtect(app)

# Configuration
UPLOAD_DIR = Path(app.config['UPLOAD_FOLDER'])
PROCESSED_DIR = Path(app.config['PROCESSED_FOLDER'])
ALLOWED_IMAGE_EXTS = {'jpg', 'jpeg', 'png', 'webp', 'heic'}
ALLOWED_VIDEO_EXTS = {'mp4', 'avi', 'mov', 'mkv'}

# Create directories
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['FRAMES_FOLDER'], exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)

def allowed_image_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTS

def allowed_video_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_VIDEO_EXTS

@app.errorhandler(413)
def request_entity_too_large(error):
    flash('File too large. Maximum size is 50MB.', 'error')
    return redirect(request.url)

@app.errorhandler(400)
def bad_request(error):
    flash('Bad request. Please try again.', 'error')
    return redirect(request.url)

@app.errorhandler(500)
def internal_error(error):
    flash('An internal error occurred. Please try again.', 'error')
    return redirect(request.url)

@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    flash('CSRF token has expired or is invalid. Please try again.', 'error')
    return redirect(request.url)

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

@app.route('/video-ui')
def video_ui():
    return render_template('video.html')

@app.route('/resize.html')
def resize_ui():
    return render_template('resize.html')

@app.route('/resize', methods=['GET', 'POST'])
def resize():
    if request.method == 'GET':
        return render_template('resize.html')
        
    app.logger.info("Resize POST request received")
    app.logger.debug(f"Request files: {request.files}")
    app.logger.debug(f"Request form: {request.form}")
    
    if 'image' not in request.files:
        app.logger.warning("No image in request.files")
        flash('No image uploaded', 'error')
        return redirect(url_for('resize_ui'))
    
    image_file = request.files['image']
    if image_file.filename == '':
        app.logger.warning("Empty filename in request")
        flash('No selected file', 'error')
        return redirect(url_for('resize_ui'))

    app.logger.info(f"Processing image: {image_file.filename}")

    try:
        # Get form data with defaults
        width = int(request.form.get('width', 800))
        height = int(request.form.get('height', 600))
        output_format = request.form.get('format', 'jpeg').lower()
        
        app.logger.info(f"Resize parameters: width={width}, height={height}, format={output_format}")

        if not allowed_image_file(image_file.filename):
            app.logger.warning(f"Invalid file type: {image_file.filename}")
            flash('Invalid file type. Please upload a valid image file (JPG, JPEG, PNG, WEBP, HEIC)', 'error')
            return redirect(url_for('resize_ui'))

        # Create a temporary file path to ensure we can properly open the image
        temp_path = UPLOAD_DIR / secure_filename(image_file.filename)
        image_file.save(temp_path)
        app.logger.info(f"Image saved temporarily to: {temp_path}")

        try:
            # Open and process the image
            img = Image.open(temp_path)
            
            # Check if we need to convert mode
            if img.mode not in ('RGB', 'RGBA') and output_format.lower() != 'png':
                img = img.convert('RGB')
                
            # Resize the image
            img = img.resize((width, height), Image.Resampling.LANCZOS)
            app.logger.info(f"Image resized to {width}x{height}")
            
            # Create output buffer
            output_buffer = io.BytesIO()
            if output_format.lower() == 'jpg' or output_format.lower() == 'jpeg':
                img.save(output_buffer, format='JPEG', quality=95)
            elif output_format.lower() == 'png':
                img.save(output_buffer, format='PNG')
            elif output_format.lower() == 'webp':
                img.save(output_buffer, format='WEBP', quality=95)
            else:
                img.save(output_buffer, format=output_format.upper(), quality=95)
                
            output_buffer.seek(0)
            app.logger.info(f"Image saved to buffer in {output_format} format")

            # Set filename
            original_name = Path(image_file.filename).stem
            download_name = f"{original_name}_resized.{output_format.lower()}"
            app.logger.info(f"Sending file as: {download_name}")
            
            # Return the file
            response = send_file(
                output_buffer,
                mimetype=f'image/{output_format.lower().replace("jpg", "jpeg")}',
                as_attachment=True,
                download_name=download_name
            )
            
            # Cleanup temp file before returning
            if temp_path.exists():
                temp_path.unlink()
                app.logger.info("Temporary file cleaned up")
                
            app.logger.info("File sent successfully")
            return response
            
        except Exception as inner_e:
            app.logger.error(f"Error processing image: {str(inner_e)}", exc_info=True)
            if temp_path.exists():
                temp_path.unlink()
            raise

    except Exception as e:
        app.logger.error(f"Resize error: {str(e)}", exc_info=True)
        flash('An error occurred during image resizing', 'error')
        return redirect(url_for('resize_ui'))

@app.route('/video', methods=['POST'])
def video():
    app.logger.info("Video POST request received")
    
    if 'video' not in request.files:
        app.logger.warning("No video in request.files")
        flash('No video uploaded', 'error')
        return redirect(url_for('video_ui'))
    
    video_file = request.files['video']
    if video_file.filename == '':
        app.logger.warning("Empty filename in request")
        flash('No selected video', 'error')
        return redirect(url_for('video_ui'))

    app.logger.info(f"Processing video: {video_file.filename}")

    try:
        fps = int(request.form.get('fps', 1))
        app.logger.info(f"FPS parameter: {fps}")
        
        if not allowed_video_file(video_file.filename):
            app.logger.warning(f"Invalid video format: {video_file.filename}")
            flash('Invalid video format. Please upload a valid video file (MP4, AVI, MOV, MKV)', 'error')
            return redirect(url_for('video_ui'))

        # Save video file to temporary location
        filename = secure_filename(video_file.filename)
        video_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        video_file.save(video_path)
        app.logger.info(f"Video saved to: {video_path}")

        # Create output directory
        session_id = str(uuid.uuid4())
        output_dir = os.path.join(app.config['FRAMES_FOLDER'], session_id)
        os.makedirs(output_dir, exist_ok=True)
        app.logger.info(f"Output directory created: {output_dir}")

        # Extract frames
        app.logger.info("Extracting frames from video")
        try:
            frame_count = extract_frames(video_path, output_dir, fps)
            app.logger.info(f"Extracted {frame_count} frames")
            
            if frame_count == 0:
                app.logger.error("No frames were extracted")
                raise ValueError("No frames were extracted from the video")

            # Create ZIP of frames
            app.logger.info("Creating ZIP file of frames")
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(output_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, output_dir)
                        zipf.write(file_path, arcname=arcname)

            zip_buffer.seek(0)
            app.logger.info("ZIP file created successfully")

            # Set filename based on original file
            original_name = Path(video_file.filename).stem
            download_name = f"{original_name}_frames.zip"

            # Send file directly
            app.logger.info(f"Sending ZIP file: {download_name}")
            response = send_file(
                zip_buffer,
                mimetype='application/zip',
                as_attachment=True,
                download_name=download_name
            )
            app.logger.info("ZIP file sent successfully")
            return response
        finally:
            # Cleanup
            app.logger.info("Cleaning up temporary files")
            try:
                if os.path.exists(video_path):
                    os.remove(video_path)
                for root, _, files in os.walk(output_dir):
                    for file in files:
                        try:
                            os.remove(os.path.join(root, file))
                        except:
                            pass
                os.rmdir(output_dir)
            except Exception as e:
                app.logger.error(f"Cleanup error: {str(e)}")

    except Exception as e:
        app.logger.error(f"Video processing error: {str(e)}", exc_info=True)
        flash('An error occurred during video processing', 'error')
        return redirect(url_for('video_ui'))

@app.route('/interpolate-ui')
def interpolate_ui():
    return render_template('interpolate.html')

@app.route('/interpolate', methods=['POST'])
def interpolate():
    app.logger.info("Interpolate POST request received")
    
    if 'video' not in request.files:
        app.logger.warning("No video in request.files")
        flash('No video uploaded', 'error')
        return redirect(url_for('interpolate_ui'))
    
    video_file = request.files['video']
    if video_file.filename == '':
        app.logger.warning("Empty filename in request")
        flash('No selected video', 'error')
        return redirect(url_for('interpolate_ui'))

    app.logger.info(f"Processing video for interpolation: {video_file.filename}")

    try:
        target_fps = int(request.form.get('target_fps', 60))
        app.logger.info(f"Target FPS parameter: {target_fps}")
        
        if not allowed_video_file(video_file.filename):
            app.logger.warning(f"Invalid video format: {video_file.filename}")
            flash('Invalid video format. Please upload a valid video file (MP4, AVI, MOV, MKV)', 'error')
            return redirect(url_for('interpolate_ui'))

        # Save video file to temporary location
        filename = secure_filename(video_file.filename)
        video_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        video_file.save(video_path)
        app.logger.info(f"Video saved to: {video_path}")

        # Create output directory
        session_id = str(uuid.uuid4())
        output_dir = os.path.join(app.config['FRAMES_FOLDER'], session_id)
        os.makedirs(output_dir, exist_ok=True)
        app.logger.info(f"Output directory created: {output_dir}")

        # Interpolate frames
        app.logger.info("Interpolating frames from video")
        try:
            frame_count = interpolate_frames(video_path, output_dir, target_fps)
            app.logger.info(f"Generated {frame_count} frames")
            
            if frame_count == 0:
                app.logger.error("No frames were generated")
                raise ValueError("No frames were generated from the video")

            # Create ZIP of frames
            app.logger.info("Creating ZIP file of frames")
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(output_dir):
                    for file in sorted(files):  # Sort to maintain frame order
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, output_dir)
                        zipf.write(file_path, arcname=arcname)

            zip_buffer.seek(0)
            app.logger.info("ZIP file created successfully")

            # Set filename based on original file
            original_name = Path(video_file.filename).stem
            download_name = f"{original_name}_interpolated_{target_fps}fps.zip"

            # Send file directly
            app.logger.info(f"Sending ZIP file: {download_name}")
            response = send_file(
                zip_buffer,
                mimetype='application/zip',
                as_attachment=True,
                download_name=download_name
            )
            app.logger.info("ZIP file sent successfully")
            return response
        finally:
            # Cleanup
            app.logger.info("Cleaning up temporary files")
            try:
                if os.path.exists(video_path):
                    os.remove(video_path)
                for root, _, files in os.walk(output_dir):
                    for file in files:
                        try:
                            os.remove(os.path.join(root, file))
                        except:
                            pass
                os.rmdir(output_dir)
            except Exception as e:
                app.logger.error(f"Cleanup error: {str(e)}")

    except Exception as e:
        app.logger.error(f"Frame interpolation error: {str(e)}", exc_info=True)
        flash('An error occurred during frame interpolation', 'error')
        return redirect(url_for('interpolate_ui'))

@app.route('/remove-bg')
def remove_bg_ui():
    return render_template('remove-bg.html')

@app.route('/remove-bg', methods=['POST'])
def remove_bg():
    app.logger.info("Background removal POST request received")
    
    if 'image' not in request.files:
        app.logger.warning("No image in request.files")
        flash('No image uploaded', 'error')
        return redirect(url_for('remove_bg_ui'))
    
    image_file = request.files['image']
    if image_file.filename == '':
        app.logger.warning("Empty filename in request")
        flash('No selected file', 'error')
        return redirect(url_for('remove_bg_ui'))

    app.logger.info(f"Processing image for background removal: {image_file.filename}")

    try:
        # Get form data
        output_format = request.form.get('format', 'png').lower()
        
        app.logger.info(f"Background removal parameters: format={output_format}")

        if not allowed_image_file(image_file.filename):
            app.logger.warning(f"Invalid file type: {image_file.filename}")
            flash('Invalid file type. Please upload a valid image file (JPG, JPEG, PNG, WEBP)', 'error')
            return redirect(url_for('remove_bg_ui'))

        # Create a temporary file path
        temp_path = UPLOAD_DIR / secure_filename(image_file.filename)
        image_file.save(temp_path)
        app.logger.info(f"Image saved temporarily to: {temp_path}")

        try:
            # Process the image to remove background
            output_buffer = remove_background(temp_path, output_format)
            app.logger.info(f"Background removed successfully")

            # Set filename
            original_name = Path(image_file.filename).stem
            download_name = f"{original_name}_nobg.{output_format.lower().replace('jpeg', 'jpg')}"
            app.logger.info(f"Sending file as: {download_name}")
            
            # Return the file
            response = send_file(
                output_buffer,
                mimetype=f'image/{output_format.lower().replace("jpg", "jpeg")}',
                as_attachment=True,
                download_name=download_name
            )
            
            # Cleanup temp file before returning
            if temp_path.exists():
                temp_path.unlink()
                app.logger.info("Temporary file cleaned up")
                
            app.logger.info("File sent successfully")
            return response
            
        except Exception as inner_e:
            app.logger.error(f"Error processing image: {str(inner_e)}", exc_info=True)
            if temp_path.exists():
                temp_path.unlink()
            raise

    except Exception as e:
        app.logger.error(f"Background removal error: {str(e)}", exc_info=True)
        flash('An error occurred during background removal', 'error')
        return redirect(url_for('remove_bg_ui'))

if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=5050,
        debug=os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    )