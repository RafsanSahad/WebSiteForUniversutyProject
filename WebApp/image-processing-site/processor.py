# processor.py
import logging
from pathlib import Path
from PIL import Image
from pillow_heif import register_heif_opener
import cv2
import os
import numpy as np

# Import rembg for background removal
from rembg import remove as remove_bg

logger = logging.getLogger(__name__)
register_heif_opener()  # Enable HEIC file support

def process_images(input_paths: list, output_dir: Path, quality: int = 85) -> list:
    """
    Convert multiple image files to JPEG format with quality optimization
    
    Args:
        input_paths: List of Path objects for input files
        output_dir: Directory to save processed images
        quality: JPEG quality (1-100)
    
    Returns:
        List of Path objects for successfully converted images
    """
    supported_extensions = ('.jpg', '.jpeg', '.png', '.webp', '.heic')
    processed_files = []
    
    try:
        output_dir.mkdir(parents=True, exist_ok=True)

        for input_path in input_paths:
            try:
                path = Path(input_path)
                if not path.exists():
                    logger.warning(f"File not found: {path}")
                    continue

                if path.suffix.lower() not in supported_extensions:
                    logger.warning(f"Unsupported file type: {path.suffix}")
                    continue

                output_path = output_dir / f"{path.stem}.jpg"
                
                with Image.open(path) as img:
                    # Convert to RGB if necessary (for PNG transparency handling)
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    
                    # Save with optimization and progressive loading
                    img.save(
                        output_path,
                        "JPEG",
                        quality=quality,
                        optimize=True,
                        progressive=True
                    )
                    processed_files.append(output_path)
                    logger.info(f"Successfully processed: {path.name}")

            except Exception as e:
                logger.error(f"Failed to process {path.name}: {str(e)}", exc_info=True)
                continue

        return processed_files

    except Exception as e:
        logger.error(f"Error in process_images: {str(e)}", exc_info=True)
        raise

def extract_frames(video_path, output_dir, fps):
    """
    Extracts frames from a video file at the specified frames per second (fps)
    and saves them to the output directory.
    """
    try:
        vidcap = cv2.VideoCapture(video_path)
        
        if not vidcap.isOpened():
            raise ValueError(f"Error opening video file: {video_path}")
        
        # Get video properties
        total_frames = int(vidcap.get(cv2.CAP_PROP_FRAME_COUNT))
        original_fps = vidcap.get(cv2.CAP_PROP_FPS)
        
        if original_fps <= 0:
            raise ValueError("Invalid video frame rate")
            
        # Calculate frame interval
        frame_interval = int(original_fps / fps) if fps else 1
        if frame_interval < 1:
            frame_interval = 1

        success, image = vidcap.read()
        count = 0
        frame_number = 0

        while success:
            if count % frame_interval == 0:
                frame_filename = os.path.join(output_dir, f"frame_{frame_number:04d}.jpg")
                # Ensure the image is in RGB format
                if len(image.shape) == 3 and image.shape[2] == 3:
                    cv2.imwrite(frame_filename, image)
                    frame_number += 1
            success, image = vidcap.read()
            count += 1

        if frame_number == 0:
            raise ValueError("No frames were extracted from the video")

        vidcap.release()
        return frame_number

    except Exception as e:
        logger.error(f"Error extracting frames: {str(e)}", exc_info=True)
        raise

def interpolate_frames(video_path, output_dir, target_fps):
    """
    Interpolates frames from a video to increase its frame rate
    and saves the frames to the output directory.
    """
    try:
        vidcap = cv2.VideoCapture(video_path)
        
        if not vidcap.isOpened():
            raise ValueError(f"Error opening video file: {video_path}")
        
        # Get video properties
        total_frames = int(vidcap.get(cv2.CAP_PROP_FRAME_COUNT))
        original_fps = vidcap.get(cv2.CAP_PROP_FPS)
        
        if original_fps <= 0:
            raise ValueError("Invalid video frame rate")
        
        logger.info(f"Original video: {total_frames} frames at {original_fps} FPS")
        logger.info(f"Target FPS: {target_fps}")
        
        if target_fps <= original_fps:
            logger.warning(f"Target FPS ({target_fps}) is less than or equal to original FPS ({original_fps})")
            # Fall back to normal extraction if not interpolating
            return extract_frames(video_path, output_dir, target_fps)
        
        # Read all frames first
        frames = []
        success, frame = vidcap.read()
        while success:
            frames.append(frame)
            success, frame = vidcap.read()
        
        vidcap.release()
        logger.info(f"Read {len(frames)} frames from video")
        
        # Calculate number of frames to generate between each pair
        frames_between = int(target_fps / original_fps) - 1
        logger.info(f"Will generate {frames_between} frames between each original pair")
        
        # Process and save frames
        frame_number = 0
        
        for i in range(len(frames) - 1):
            # Save original frame
            frame_filename = os.path.join(output_dir, f"frame_{frame_number:04d}.jpg")
            cv2.imwrite(frame_filename, frames[i])
            frame_number += 1
            
            # Generate interpolated frames
            for j in range(1, frames_between + 1):
                alpha = j / (frames_between + 1)  # Interpolation factor
                interpolated_frame = cv2.addWeighted(frames[i], 1 - alpha, frames[i+1], alpha, 0)
                frame_filename = os.path.join(output_dir, f"frame_{frame_number:04d}.jpg")
                cv2.imwrite(frame_filename, interpolated_frame)
                frame_number += 1
        
        # Save last frame
        if len(frames) > 0:
            frame_filename = os.path.join(output_dir, f"frame_{frame_number:04d}.jpg")
            cv2.imwrite(frame_filename, frames[-1])
            frame_number += 1
        
        if frame_number == 0:
            raise ValueError("No frames were generated")
        
        logger.info(f"Generated total of {frame_number} frames")
        return frame_number
    
    except Exception as e:
        logger.error(f"Error interpolating frames: {str(e)}", exc_info=True)
        raise

def resize_image(image_file, width, height, output_format):
    """
    Resizes the given image to the specified width and height and returns
    a BytesIO stream of the processed image.
    """
    try:
        img = Image.open(image_file)
        resized_img = img.resize((width, height), Image.Resampling.LANCZOS)

        from io import BytesIO
        img_io = BytesIO()
        resized_img.save(img_io, format=output_format.upper(), quality=95)
        img_io.seek(0)
        return img_io

    except Exception as e:
        logger.error(f"Error resizing image: {str(e)}", exc_info=True)
        raise

def remove_background(image_file, output_format='png'):
    """
    Removes the background from an image using rembg library
    
    Args:
        image_file: Path to the input image file
        output_format: Output format to save the processed image (png, jpg, webp)
    
    Returns:
        BytesIO object containing the processed image
    """
    try:
        from io import BytesIO
        
        # Open the image
        img = Image.open(image_file)
        logger.info(f"Processing image for background removal: {image_file}")
        
        # Remove background
        result = remove_bg(img)
        logger.info("Background removal completed")
        
        # If jpg format is requested, need to add white background
        if output_format.lower() == 'jpg' or output_format.lower() == 'jpeg':
            # Create white background
            white_bg = Image.new("RGB", result.size, (255, 255, 255))
            # Paste the foreground onto the white background using the alpha as mask
            white_bg.paste(result, (0, 0), result)
            result = white_bg
            
        # Save to BytesIO
        img_io = BytesIO()
        if output_format.lower() == 'png':
            result.save(img_io, format='PNG')
        elif output_format.lower() in ('jpg', 'jpeg'):
            result.save(img_io, format='JPEG', quality=95)
        elif output_format.lower() == 'webp':
            result.save(img_io, format='WEBP', quality=95, lossless=True)
        else:
            result.save(img_io, format='PNG')
            
        img_io.seek(0)
        return img_io
        
    except Exception as e:
        logger.error(f"Error removing background: {str(e)}", exc_info=True)
        raise