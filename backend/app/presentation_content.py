"""Render approved, bounded timeline content as one editable widescreen slide."""
from io import BytesIO
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor

PHASE_SCHEMA = {"type": "object", "additionalProperties": False,
    "required": ["period", "title", "items"], "properties": {
        "period": {"type": "string", "minLength": 1, "maxLength": 24},
        "title": {"type": "string", "minLength": 1, "maxLength": 40},
        "items": {"type": "array", "minItems": 1, "maxItems": 5,
                  "items": {"type": "string", "minLength": 1, "maxLength": 90}}}}
PRESENTATION_SCHEMA = {"type": "object", "additionalProperties": False,
    "required": ["title", "phases"], "properties": {
        "title": {"type": "string", "minLength": 1, "maxLength": 50},
        "subtitle": {"type": "string", "maxLength": 120},
        "phases": {"type": "array", "minItems": 1, "maxItems": 4, "items": PHASE_SCHEMA}}}


def render_timeline(arguments: dict) -> bytes:
    from jsonschema import validate
    validate(arguments, PRESENTATION_SCHEMA)
    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(16), Inches(9)
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = RGBColor.from_string('101C2C')

    def label(x, y, w, h, value, size, color='FFFFFF', bold=False):
        box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        frame = box.text_frame
        frame.word_wrap = True
        frame.margin_left = frame.margin_right = 0
        frame.margin_top = frame.margin_bottom = 0
        p = frame.paragraphs[0]
        p.text = value
        p.font.size = Pt(size)
        p.font.bold = bold
        p.font.color.rgb = RGBColor.from_string(color)
        p.font.name = 'Aptos'
        p.line_spacing = 1.05
        p.space_after = Pt(0)
    label(.7, .5, 14.6, .9, arguments['title'], 34, bold=True)
    label(.7, 1.5, 14.6, .8, arguments.get('subtitle', ''), 18, 'B7C7D9')
    phases = arguments['phases']
    width = 14.6 / len(phases)
    for i, phase in enumerate(phases):
        x = .7 + i * width
        label(x, 2.7, width-.3, .5, phase['period'], 17, '64DBC4', True)
        label(x, 3.4, width-.3, 1.0, phase['title'], 22, bold=True)
        for j, item in enumerate(phase['items']):
            label(x, 4.55+j*.72, width-.35, .7, item, 14, 'DCE6F1')
    result = BytesIO()
    deck.save(result)
    return result.getvalue()
