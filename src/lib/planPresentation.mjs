// Copy for the existing title/description fields. The video operation performs
// the complete review; its activities are not extra executable steps.
export function videoReviewPlanContent(step = {}) {
  if (step.operation === "frameio.assistant.review") return {
    title: "Review the video with Frame.io AI Assistant",
    iWill: "send your review instructions and selected video to Frame.io’s own AI Assistant through AURA, then return its actual response with timestamps and production corrections. Preserve the assistant’s stated audio and coverage limitations. Connect its sign-in session before starting",
  };
  if (!["frameio.video.review", "intelligence.video.review"].includes(step.operation)) return null;
  const source = step.operation === "frameio.video.review" ? "selected Frame.io video version" : "uploaded video";
  return {
    title: "Review the video and prepare production feedback",
    iWill: `review the ${source} across its full timeline using sampled frames and audio with AURA Intelligence, following your instructions. Identify errors, inconsistencies, poor transitions, unclear messaging, incorrect graphics, spelling mistakes, audio problems, and visual distractions. Return feedback in chronological order with timestamps, observed issues, and recommended production fixes. Visual timestamps come from sampled frames; brief defects may be missed and audio times are approximate`,
  };
}

// Labels follow the actual operation, never incidental words in its reason.
export function operationStepTitle(step = {}, tool = "the app") {
  const operation = String(step.operation || "");
  const video = videoReviewPlanContent(step);
  if (video) return video.title;
  if (operation === "frameio.identity.get") return "Check the connected Frame.io account";
  if (operation === "frameio.accounts.list") return "Find the accessible Frame.io accounts";
  if (operation === "frameio.file.get") return "Read the selected Frame.io video version";
  if (operation === "report.compose") return "Generate report with ChatGPT";
  if (operation === "meta-ads-simulated.review.get") return "Run the Meta Ads simulation";
  if (operation === "klaviyo-simulated.lifecycle.get") return "Run the Klaviyo simulation";
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
  const verifying = /^(?:verify|confirm|check (?:the )?saved|read back)/i.test(step.reason || "");
  const titles = {
    "sheets.campaign_report.create": "Create and check the campaign report",
    "sheets.campaign_report.get": "Verify the saved campaign workbook",
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

