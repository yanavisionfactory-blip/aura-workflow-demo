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

// References are filled by earlier workflow steps. A wording suggestion must not
// accidentally turn live data into invented static copy.
export const dynamicReferences = (value) => String(value || "").match(/\{\{[^}]+\}\}/g) || [];

export function assertReferencesPreserved(before, after) {
  for (const reference of dynamicReferences(before)) {
    if (!String(after || "").includes(reference)) {
      throw new Error("AURA kept the live information in place. Edit it on the preview if you want to replace it.");
    }
  }
}

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
    assertReferencesPreserved(phase.period, slide.period);
    assertReferencesPreserved(phase.title, slide.title);
    phase.items?.forEach((item, itemIndex) => assertReferencesPreserved(item, slide.items[itemIndex]));
    return { ...phase, period: slide.period, title: slide.title, items: slide.items };
  });
  assertReferencesPreserved(args.title, suggestion.title);
  assertReferencesPreserved(args.subtitle, suggestion.subtitle);
  return { ...args, title: suggestion.title, subtitle: suggestion.subtitle, phases };
}
