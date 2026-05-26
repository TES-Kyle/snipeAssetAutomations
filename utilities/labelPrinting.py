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
    logger.debug("sendToPrinter called: path=%s", path)
    # Load printer settings and render data for the target model.
    settings = json.loads(open(str(os.path.dirname(os.path.realpath(__file__)))+"/settings.json").read())
    logger.debug("sendToPrinter: printerType=%s, labelName=%s, labelsPerPrint=%s, printerIP=%s",
                 settings.get("printerType"), settings.get("labelName"),
                 settings.get("labelsPerPrint"), settings.get("printerIP"))
    filename = path
    # Prepare the rasterized print payload for the configured printer.
    printer = BrotherQLRaster(settings["printerType"])
    logger.debug("sendToPrinter: BrotherQLRaster created for %s", settings["printerType"])
    print_data = brother_ql.brother_ql_create.convert(printer, [filename], settings["labelName"])
    logger.debug("sendToPrinter: print_data converted, sending %s copies", settings.get("labelsPerPrint"))
    try:
        # Print multiple copies as configured.
        for i in range(int(settings["labelsPerPrint"])):
            logger.info("sendToPrinter: sending copy %s of %s to %s", i + 1, settings["labelsPerPrint"], settings["printerIP"])
            send(print_data, settings["printerIP"])
        logger.info("sendToPrinter: all copies sent successfully for %s", path)
    except Exception as e:
        logger.exception("Unable to print label")
        messagebox.showerror("Print Label Failed", f"Unable to print label.\n\n{e}")



def createImage(values):
    """Render a label image with text rows and a barcode for the asset tag.

    Args:
        values: List of strings to render on the label (first entry is asset tag).
    """
    configure_logging()
    logger.debug("createImage called: %s values, values=%s", len(values), values)
    # Load label sizing settings from the config file.
    settings = json.loads(open(str(os.path.dirname(os.path.realpath(__file__)))+"/settings.json").read())
    image_width = int(settings["labelWidth"])
    image_height = int(settings["labelHeight"])
    logger.debug("createImage: image dimensions width=%s, height=%s", image_width, image_height)

    # Resolve font path for the current platform.
    font_name = get_font_path()
    logger.debug("createImage: using font_path=%s", font_name)

    # Create a new image with white background.
    image = Image.new("RGB", (image_width, image_height), "white")
    draw = ImageDraw.Draw(image)
    logger.debug("createImage: blank %sx%s image created", image_width, image_height)

    # Find the maximum font size for each line of text.
    max_font_size = 1
    variables = values
    assetTag = variables[0]
    logger.debug("createImage: asset tag=%s, %s text rows to render", assetTag, len(variables))
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
        logger.debug("createImage: var=%s computed font_size=%s", var, max_font_size - 1)

    logger.debug("createImage: font_sizes=%s", font_sizes)

    # Calculate the y-position for each text row.
    y_positions = [i * (image_height / len(variables)) for i in range(len(variables))]
    logger.debug("createImage: y_positions=%s", y_positions)

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
        logger.debug("createImage: drawing row %s var=%s at x=%s y=%s font_size=%s", i, var, x_position, y_position, font_size)
        draw.text((x_position, y_position), var, fill="black", font=font)

    # Generate and paste the barcode onto the label.
    logger.debug("createImage: generating Code128 barcode for asset_tag=%s", assetTag)
    render_options = {"module_width": 0.5, "module_height": 7, "font_size": 5, "text_distance": 1.5}
    barcode = Code128(assetTag, writer=ImageWriter())
    barcode_image = barcode.render(render_options)
    barcode_width, barcode_height = barcode_image.size
    logger.debug("createImage: barcode rendered size=%sx%s", barcode_width, barcode_height)
    barcode_x = image_width / 2 + (image_width / 2 - barcode_width) / 2
    barcode_y = (image_height - barcode_height) / 2
    logger.debug("createImage: pasting barcode at x=%s y=%s", barcode_x, barcode_y)
    image.paste(barcode_image, (int(barcode_x), int(barcode_y)))

    # Rotate and save the label image for printing.
    logger.debug("createImage: rotating image -90 degrees and saving")
    image = image.rotate(-90, expand=True)
    save_path = str(os.path.dirname(os.path.dirname((os.path.realpath(__file__))))) + "/utilities/barcode-label.jpg"
    image.save(save_path, "JPEG")
    logger.info("Barcode label image generated: %s", assetTag)
    logger.debug("createImage: label saved to %s", save_path)
    if settings["Default Print (BOOL)"] == "1":
        logger.info("createImage: auto-print enabled; sending to printer")
        sendToPrinter(os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "utilities/barcode-label.jpg"))



def get_font_path():
    """Return a platform-appropriate font path for label rendering.

    Returns:
        Absolute path to the font file to use for label text.

    Raises:
        OSError: When the current platform is not supported.
    """
    logger.debug("get_font_path called, os.name=%s", os.name)
    if os.name == 'nt':  # Windows
        path = "C:\\WINDOWS\\FONTS\\ARIBLK.TTF"
        logger.debug("get_font_path: Windows platform, font_path=%s", path)
        return path
    elif os.name == 'posix':  # macOS and Unix-like systems
        # os.uname().sysname will give you more specific information
        sysname = os.uname().sysname.lower()
        logger.debug("get_font_path: POSIX platform, sysname=%s", sysname)
        if 'darwin' in sysname:
            path = "/Library/Fonts/Arial Black.ttf"
            logger.debug("get_font_path: macOS detected, font_path=%s", path)
            return path
        else:
            # Handle other POSIX systems or raise an error
            logger.error("get_font_path: unsupported POSIX system sysname=%s", sysname)
            raise OSError("Unsupported POSIX operating system")
    else:
        logger.error("get_font_path: unsupported operating system os.name=%s", os.name)
        raise OSError("Unsupported operating system")
