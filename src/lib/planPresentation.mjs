// Labels follow the actual operation, never incidental words in its reason.
export function operationStepTitle(step = {}, tool = "the app") {
  const operation = String(step.operation || "");
  if (operation === "website.source.inspect") {
    const names = { agency: "Check the agency's client evidence", sitemap: "Read the existing sitemap", cms: "Confirm the selected website's CMS", page: "Read the existing website page" };
    return names[step.arguments?.role] || "Read the website source";
  }
  if (operation === "website.content.prepare") return "Prepare the five-page content package in AURA";
  if (operation === "executive.source.analyze") {
    const names = { google_ads: "Google Ads", google_business_profile: "Google Business Profile", facebook: "Facebook", instagram: "Instagram", linkedin: "LinkedIn", x: "X / Twitter", crm: "CRM", appointments: "Appointment system", analytics: "Analytics", reporting: "Reporting and goals" };
    return `Process the simulated ${names[step.arguments?.source_key] || "executive review"} export`;
  }
  if (operation === "executive.review.prepare") return "Prepare the executive review in AURA";
  if (operation === "weekly.source.analyze") {
    const source = { google: "Google Ads", meta: "Meta Ads", klaviyo: "Klaviyo" }[step.arguments?.source_key] || "marketing";
    return `Process the synthetic ${source} export`;
  }
  if (operation === "weekly.review.prepare") return "Prepare the weekly review and draft variants";
  if (operation === "mailchimp.audience.get") return "Verify the selected client audience";
  if (operation === "mailchimp.campaign.draft.create") return "Create an unsent Mailchimp campaign";
  if (operation === "mailchimp.campaign.content.set") return "Save and verify the email content";
  const verifying = /^(?:verify|confirm|check (?:the )?saved|read back)/i.test(step.reason || "");
  const titles = {
    "get_report_schema": "Read the provider report schema",
    "execute_report": "Run the provider report",
    "seo.crawl.analyze": "Analyze the supplied Screaming Frog exports",
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
