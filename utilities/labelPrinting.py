"""Label image generation and printer dispatch helpers.

Generates a barcode label image (text + Code128) and sends it to
the configured Brother label printer using settings.json.
"""

import json
import logging
import os
import brother_ql
from brother_ql.backends.helpers import send
from brother_ql.raster import BrotherQLRaster
from PIL import Image, ImageDraw, ImageFont
from barcode.codex import Code128
from barcode.writer import ImageWriter
from tkinter import messagebox

from utilities.logging_utils import configure_logging

logger = logging.getLogger(__name__)


def sendToPrinter(path):
    """Send a pre-rendered label image to the configured Brother printer.

    Args:
        path: Filesystem path to the label image.
    """
    configure_logging()
    # Load printer settings and render data for the target model.
    settings = json.loads(open(str(os.path.dirname(os.path.realpath(__file__)))+"/settings.json").read())
    filename = path
    # Prepare the rasterized print payload for the configured printer.
    printer = BrotherQLRaster(settings["printerType"])
    print_data = brother_ql.brother_ql_create.convert(printer, [filename], settings["labelName"])
    try:
        # Print multiple copies as configured.
        for i in range(int(settings["labelsPerPrint"])):
            send(print_data, settings["printerIP"])
    except Exception as e:
        logger.exception("Unable to print label")
        messagebox.showerror("Print Label Failed", f"Unable to print label.\n\n{e}")



def createImage(values):
    """Render a label image with text rows and a barcode for the asset tag.

    Args:
        values: List of strings to render on the label (first entry is asset tag).
    """
    configure_logging()
    # Load label sizing settings from the config file.
    settings = json.loads(open(str(os.path.dirname(os.path.realpath(__file__)))+"/settings.json").read())
    image_width = int(settings["labelWidth"])
    image_height = int(settings["labelHeight"])

    # Resolve font path for the current platform.
    font_name = get_font_path()

    # Create a new image with white background.
    image = Image.new("RGB", (image_width, image_height), "white")
    draw = ImageDraw.Draw(image)

    # Find the maximum font size for each line of text.
    max_font_size = 1
    variables = values
    assetTag = variables[0]
    font_sizes = []
    for var in variables:
        font_size = 1
        font = ImageFont.truetype(font_name, font_size)
        text_bbox = draw.textbbox((0, 0), var, font=font)
        while text_bbox[2] < image_width / 2 and text_bbox[3] < image_height / len(variables) and font_size <= 100:
            max_font_size = font_size
            font_size += 1
            font = ImageFont.truetype(font_name, font_size)
            text_bbox = draw.textbbox((0, 0), var, font=font)
        font_sizes.append(max_font_size - 1)

    # Calculate the y-position for each text row.
    y_positions = [i * (image_height / len(variables)) for i in range(len(variables))]

    # Draw text values on the left half of the label.
    for i, var in enumerate(variables):
        font_size = font_sizes[i]
        font = ImageFont.truetype(font_name, font_size)
        text_bbox = draw.textbbox((0, 0), var, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        # Center each line within its row area.
        x_position = (image_width / 2 - text_width) / 2
        y_position = y_positions[i] + (image_height / len(variables) - text_height) / 2 - 40
        draw.text((x_position, y_position), var, fill="black", font=font)

    # Generate and paste the barcode onto the label.
    render_options = {"module_width": 0.5, "module_height": 7, "font_size": 5, "text_distance": 1.5}
    barcode = Code128(assetTag, writer=ImageWriter())
    barcode_image = barcode.render(render_options)
    barcode_width, barcode_height = barcode_image.size
    barcode_x = image_width / 2 + (image_width / 2 - barcode_width) / 2
    barcode_y = (image_height - barcode_height) / 2
    image.paste(barcode_image, (int(barcode_x), int(barcode_y)))

    # Rotate and save the label image for printing.
    image = image.rotate(-90, expand=True)
    image.save(str(os.path.dirname(os.path.dirname((os.path.realpath(__file__))))) + "/utilities/barcode-label.jpg", "JPEG")
    logger.info("Barcode label image generated: %s", assetTag)
    if settings["Default Print (BOOL)"] == "1":
        sendToPrinter(os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "utilities/barcode-label.jpg"))



def get_font_path():
    """Return a platform-appropriate font path for label rendering."""
    if os.name == 'nt':  # Windows
        return "C:\\WINDOWS\\FONTS\\ARIBLK.TTF"
    elif os.name == 'posix':  # macOS and Unix-like systems
        # os.uname().sysname will give you more specific information
        if 'darwin' in os.uname().sysname.lower():
            return "/Library/Fonts/Arial Black.ttf"
        else:
            # Handle other POSIX systems or raise an error
            raise OSError("Unsupported POSIX operating system")
    else:
        raise OSError("Unsupported operating system")
