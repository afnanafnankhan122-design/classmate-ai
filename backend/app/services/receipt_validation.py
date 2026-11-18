from io import BytesIO
import warnings

from PIL import Image, UnidentifiedImageError


MAX_RECEIPT_PIXELS = 25_000_000
ALLOWED_FORMATS = {
    ".jpg": ("JPEG", "image/jpeg"),
    ".jpeg": ("JPEG", "image/jpeg"),
    ".png": ("PNG", "image/png"),
}


def validate_receipt_image(
    content: bytes,
    filename: str | None,
    content_type: str | None,
) -> tuple[str, str]:
    extension = ""
    if filename:
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        extension = f".{extension}"
    expected = ALLOWED_FORMATS.get(extension)
    if expected is None:
        raise ValueError("Receipt must be a JPG, JPEG, or PNG image.")
    image_format, expected_content_type = expected
    if content_type != expected_content_type:
        raise ValueError("Receipt MIME type does not match the supported image format.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(BytesIO(content))
            if image.format != image_format:
                raise ValueError("Receipt file content does not match its extension.")
            if image.width * image.height > MAX_RECEIPT_PIXELS:
                raise ValueError("Receipt image dimensions are too large.")
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Receipt file is not a valid, readable image.") from exc

    return extension[1:], expected_content_type
