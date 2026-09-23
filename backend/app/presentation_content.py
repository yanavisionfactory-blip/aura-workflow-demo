"""Render approved, bounded presentation content as editable widescreen slides."""
from io import BytesIO

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

PHASE_SCHEMA = {"type": "object", "additionalProperties": False,
    "required": ["period", "title", "items"], "properties": {
        "period": {"type": "string", "minLength": 1, "maxLength": 24},
        "title": {"type": "string", "minLength": 1, "maxLength": 40},
        "items": {"type": "array", "minItems": 1, "maxItems": 5,
                  "items": {"type": "string", "minLength": 1, "maxLength": 90}},
        "scene": {"type": "string", "enum": ["rain_window", "paper_boat", "lantern"]}}}
PRESENTATION_SCHEMA = {"type": "object", "additionalProperties": False,
    "required": ["title", "phases"], "properties": {
        "title": {"type": "string", "minLength": 1, "maxLength": 50},
        "subtitle": {"type": "string", "maxLength": 120},
        "layout": {"type": "string", "enum": ["timeline", "slides"]},
        "phases": {"type": "array", "minItems": 1, "maxItems": 4, "items": PHASE_SCHEMA}}}


def render_timeline(arguments: dict) -> bytes:
    from jsonschema import validate
    validate(arguments, PRESENTATION_SCHEMA)
    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(16), Inches(9)
    def label(slide, x, y, w, h, value, size, color='FFFFFF', bold=False):
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

    phases = arguments['phases']
    if arguments.get('layout') == 'slides':
        accents = ('64DBC4', '78A9FF', 'F2C14E', 'C69CFF')
        for index, phase in enumerate(phases):
            slide = deck.slides.add_slide(deck.slide_layouts[6])
            slide.background.fill.solid()
            slide.background.fill.fore_color.rgb = RGBColor.from_string('101C2C')
            accent = accents[index % len(accents)]
            illustrated = bool(phase.get("scene"))
            if illustrated:
                from .poem_art import render_poem_scene

                slide.shapes.add_picture(BytesIO(render_poem_scene(phase["scene"])),
                                         Inches(8.25), Inches(1.1),
                                         width=Inches(6.85), height=Inches(6.7))
            label(slide, .75, .5, 12.5, .45, arguments['title'], 15, 'B7C7D9', True)
            label(slide, .75, 1.25, 14.4, .45, phase['period'].upper(), 15, accent, True)
            label(slide, .75, 1.85, 14.4, 1.0, phase['title'], 34, 'FFFFFF', True)
            for item_index, item in enumerate(phase['items']):
                label(
                    slide, 1.0, 3.15 + item_index * .92,
                    6.7 if illustrated else 13.8, .8,
                    item if illustrated else f"•  {item}", 19 if illustrated else 18, 'DCE6F1'
                )
            label(slide, .75, 8.25, 13.2, .3, arguments.get('subtitle', ''), 10, '8295AA')
            label(slide, 14.2, 8.25, 1.0, .3, f"{index + 1} / {len(phases)}", 10, accent, True)
    else:
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor.from_string('101C2C')
        label(slide, .7, .5, 14.6, .9, arguments['title'], 34, bold=True)
        label(slide, .7, 1.5, 14.6, .8, arguments.get('subtitle', ''), 18, 'B7C7D9')
        width = 14.6 / len(phases)
        for i, phase in enumerate(phases):
            x = .7 + i * width
            label(slide, x, 2.7, width-.3, .5, phase['period'], 17, '64DBC4', True)
            label(slide, x, 3.4, width-.3, 1.0, phase['title'], 22, bold=True)
            for j, item in enumerate(phase['items']):
                label(slide, x, 4.55+j*.72, width-.35, .7, item, 14, 'DCE6F1')
    result = BytesIO()
    deck.save(result)
    return result.getvalue()
