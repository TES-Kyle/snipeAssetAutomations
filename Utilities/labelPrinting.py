import brother_ql
from brother_ql.raster import BrotherQLRaster
from brother_ql.backends.helpers import send
from PIL import Image, ImageDraw, ImageFont
from barcode import Code128
from barcode.writer import ImageWriter
import json
import os


def sendToPrinter(path):
    settings = json.loads(open(str(os.path.dirname(os.path.realpath(__file__)))+"/settings.json").read())
    filename = path
    printer = BrotherQLRaster(settings["printerType"])
    print_data = brother_ql.brother_ql_create.convert(printer, [filename], settings["labelName"])
    for i in range(int(settings["labelsPerPrint"])):
        send(print_data, settings["printerIP"])


def createImage(values):
    settings = json.loads(open(str(os.path.dirname(os.path.realpath(__file__)))+"/settings.json").read())
    image_width = int(settings["labelWidth"])
    image_height = int(settings["labelHeight"])

    font_name = get_font_path()

    # Create a new image with white background
    image = Image.new("RGB", (image_width, image_height), "white")
    draw = ImageDraw.Draw(image)

    # Find the maximum font size for the variables
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

    # Calculate the y-position for each variable
    y_positions = [i * (image_height / len(variables)) for i in range(len(variables))]

    # Draw the variables on the label
    for i, var in enumerate(variables):
        font_size = font_sizes[i]
        font = ImageFont.truetype(font_name, font_size)
        text_bbox = draw.textbbox((0, 0), var, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        x_position = (image_width / 2 - text_width) / 2
        y_position = y_positions[i] + (image_height / len(variables) - text_height) / 2 - 40
        draw.text((x_position, y_position), var, fill="black", font=font)

    # Generate and paste the barcode onto the label
    render_options = {"module_width": 0.5, "module_height": 7, "font_size": 5, "text_distance": 1.5}
    barcode = Code128(assetTag, writer=ImageWriter())
    barcode_image = barcode.render(render_options)
    barcode_width, barcode_height = barcode_image.size
    barcode_x = image_width / 2 + (image_width / 2 - barcode_width) / 2
    barcode_y = (image_height - barcode_height) / 2
    image.paste(barcode_image, (int(barcode_x), int(barcode_y)))

    # Save the image as JPEG
    image = image.rotate(-90, expand=True)
    image.save(str(os.path.dirname(os.path.realpath(__file__))) + "/" + "barcode-label.jpg", "JPEG")


def get_font_path():
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
