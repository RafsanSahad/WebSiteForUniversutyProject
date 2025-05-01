# processor.py
import logging
from pathlib import Path
from PIL import Image
from pillow_heif import register_heif_opener

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

def resize_image(input_path: Path, output_path: Path, 
                width: int, height: int, 
                format: str = 'JPEG', quality: int = 85) -> None:
    """
    Resize an image while maintaining aspect ratio and save in specified format
    
    Args:
        input_path: Path to source image
        output_path: Path to save resized image
        width: Target width in pixels
        height: Target height in pixels
        format: Output format (JPEG, PNG, WEBP)
        quality: Output quality (1-100)
    """
    try:
        with Image.open(input_path) as img:
            # Maintain aspect ratio
            original_width, original_height = img.size
            ratio = min(width/original_width, height/original_height)
            new_size = (int(original_width * ratio), int(original_height * ratio))
            
            # High-quality downsampling
            img = img.resize(new_size, Image.LANCZOS)
            
            # Preserve transparency for PNG
            if format == 'PNG' and img.mode in ('RGBA', 'LA'):
                img.save(output_path, format, quality=quality, optimize=True)
            else:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                img.save(output_path, format, quality=quality, optimize=True)
            
            logger.info(f"Resized {input_path.name} to {new_size[0]}x{new_size[1]}")

    except Exception as e:
        logger.error(f"Resize failed for {input_path.name}: {str(e)}", exc_info=True)
        raise RuntimeError(f"Image resize failed: {str(e)}") from e