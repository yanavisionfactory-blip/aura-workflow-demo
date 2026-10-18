// Labels follow the actual operation, never incidental words in its reason.
export function operationStepTitle(step = {}, tool = "the app") {
  const operation = String(step.operation || "");
  const verifying = /^(?:verify|confirm|check (?:the )?saved|read back)/i.test(step.reason || "");
  const titles = {
    "wordpress-org.update-post": "Save the unpublished article",
    "wordpress-org.search-posts": verifying ? "Verify the saved articles" : "Find existing articles",
    "wordpress-org.list-media-options": "Find existing images",
    "rankmath.post_analysis.get": "Review the article's SEO",
    "rankmath.post_seo.get": verifying ? "Verify saved SEO settings" : "Read current SEO settings",
    "rankmath.post_seo.update": "Save the SEO settings",
    "imagify.stats.get": "Check image optimization totals",
    "imagify.media_status.get": "Check the image's status",
    "imagify.media.preview": "Check the image quota",
    "imagify.media.optimize": "Optimize the selected image",
    "google-docs.get-document": "Read the Google Doc",
    "google-docs.create-document": "Save the Google Doc",
    "google-ads.generate-keyword-ideas": "Research keyword ideas",
    "google-ads.list-account-id-options": "Check the connected Ads account",
  };
  if (titles[operation]) return titles[operation];
  if (/(?:[.-])(?:get|list|search|read|fetch|retrieve)(?:[.-]|$)/i.test(operation)) {
    return verifying ? `Verify the saved result in ${tool}` : `Read from ${tool}`;
  }
  return null;
}

export function removeStepInstruction(step = {}, index = 0) {
  return `Remove step ${index + 1} (“${step.action || step.reason || step.title || "this step"}”) from the plan. Preserve the other steps unless they require an output from the removed step.`;
}

export function weatherStepTitle(step = {}) {
  const requested = String(step.arguments?.date || "").trim().toLowerCase();
  const reason = String(step.reason || "").toLowerCase();
  if (requested === "today" || (!requested && /\btoday\b/.test(reason))) {
    return "Check today's weather";
  }
  if (requested === "tomorrow" || (!requested && /\btomorrow\b/.test(reason))) {
    return "Check tomorrow's weather";
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(requested)) {
    return `Check weather for ${requested}`;
  }
  return "Check the weather";
}
