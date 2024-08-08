import Utilities.Key as Key
import brother_ql
from brother_ql.raster import BrotherQLRaster
from brother_ql.backends.helpers import send
from PIL import Image, ImageDraw, ImageFont
from barcode import Code128
from barcode.writer import ImageWriter
import requests
import json
import os


# API URL of Snipe-IT Server -- this one includes the specific API call of listing hardware info by asset tag
url = Key.API_URL_Base + "hardware/bytag/"

# API Key which can be created in your SnipeIT Account, place it inbetween quotes as one line
# REF: https://snipe-it.readme.io/reference/generating-api-tokens
token = Key.API_Key


# Headers used in the request library to pass the authorization bearer token
headers = {
    "accept": "application/json",
    "Authorization": "Bearer " + token,
    "content-type": "application/json"
}

# Printer Ident
PRINTER_IDENTIFIER = Key.printer_ip
printer = BrotherQLRaster('QL-720NW')

# are we using pre-cut stickers or one long tape
Pre_Cut = False  # ######## !!!!! change this if needed !!!!!

# how many stickers to print per computer
copies = 2

def sendToPrinter(path):
    filename = path
    printer = BrotherQLRaster('QL-720NW')
    print("SENDING TO PRINTER")
    # print("PATH: " + path)
    if (Pre_Cut):
        print_data = brother_ql.brother_ql_create.convert(printer, [filename], '62x100')
    else:
        print_data = brother_ql.brother_ql_create.convert(printer, [filename], '62')
    send(print_data, PRINTER_IDENTIFIER)

# Primary Asset Info function, accepts an asset tag
def getAssetInfo(assetTag):
    # Makes API request, combines Asset Tag that was passed through the function into the URL -- requires requests header
    response = requests.get(url + assetTag, headers=headers)
    # Loads the response in text format into a readable format -- requires import json header
    jsonData = json.loads(response.text)
    # Returns the parsed JSON data back to where the function was called
    return jsonData


def createImage(values):
    # Set up image dimensions and properties
    if (Pre_Cut):
        image_width = 1109  # 100mm at 300 dpi
    else:
        image_width = 4 * 300  # 4 inches at 300 dpi
    image_height = 696  # 62mm at 300 dpi
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

    # Calculate the maximum height for each variable
    max_text_height = min(image_height / len(variables), max(font_sizes))

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
    sendToPrinter(str(os.path.dirname(os.path.realpath(__file__))) + "/" + "barcode-label.jpg")


def printCustomLabel(asset_tag, *args):
    print("Printing custom label")


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