from . import (pdf_text, pdf_diagram, html_parser, xlsx_parser, docx_parser,
               pptx_parser, json_parser, image_parser)

PARSERS = {
    "pdf_text": pdf_text.parse,
    "pdf_diagram": pdf_diagram.parse,
    "pdf_scan": image_parser.parse_scan,
    "html": html_parser.parse,
    "xlsx": xlsx_parser.parse,
    "docx": docx_parser.parse,
    "pptx": pptx_parser.parse,
    "json": json_parser.parse,
    "image_screenshot": image_parser.parse,
    "image_diagram": image_parser.parse,
}
