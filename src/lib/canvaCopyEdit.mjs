export const presentationCopySchema = {
  type: "object",
  additionalProperties: false,
  required: ["title", "subtitle", "slides"],
  properties: {
    title: { type: "string" },
    subtitle: { type: "string" },
    slides: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["period", "title", "items"],
        properties: {
          period: { type: "string" },
          title: { type: "string" },
          items: { type: "array", items: { type: "string" } },
        },
      },
    },
  },
};

export function applyPresentationCopy(args, suggestion) {
  const original = Array.isArray(args.phases) ? args.phases : [];
  if (!suggestion || typeof suggestion.title !== "string" || typeof suggestion.subtitle !== "string"
    || !Array.isArray(suggestion.slides) || suggestion.slides.length !== original.length) {
    throw new Error("AURA could not apply that change. Please try again or edit the slide directly.");
  }
  const phases = original.map((phase, index) => {
    const slide = suggestion.slides[index];
    if (!slide || typeof slide.period !== "string" || typeof slide.title !== "string"
      || !Array.isArray(slide.items) || slide.items.some((item) => typeof item !== "string")) {
      throw new Error("AURA could not apply that change. Please try again or edit the slide directly.");
    }
    return { ...phase, period: slide.period, title: slide.title, items: slide.items };
  });
  return { ...args, title: suggestion.title, subtitle: suggestion.subtitle, phases };
}
