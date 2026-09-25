const labelForKey = (key) => String(key || "")
  .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
  .replace(/[_-]+/g, " ")
  .replace(/^./, (character) => character.toUpperCase());

const controlForValue = (value) => {
  if (typeof value === "boolean") return "checkbox";
  if (typeof value === "number") return "number";
  if (value && typeof value === "object") return "json";
  return "text";
};

const reviewKindForOperation = (operation = "") => {
  const lowered = String(operation).toLowerCase();
  if (lowered === "gmail.send" || lowered.includes("email")) return "email";
  if (lowered === "canva.presentation.create" || lowered.includes("presentation")) return "presentation";
  if (lowered.startsWith("jira.") || ["ticket", "issue"].some((word) => lowered.includes(word))) return "ticket";
  if (lowered === "slack.post" || ["message", "notify"].some((word) => lowered.includes(word))) return "message";
  if (lowered.startsWith("calendar.") || lowered.includes("event")) return "calendar";
  if (lowered.startsWith("docs.") || ["document", "report", "notion.page", "blocks.children"].some((word) => lowered.includes(word))) return "document";
  if (["sheets.", "airtable.", "hubspot.", "contact", "company"].some((word) => lowered.includes(word))) return "records";
  if (["campaign", "tiktok", "publish", "upload"].some((word) => lowered.includes(word))) return "content";
  if (lowered.startsWith("canva.")) return "design";
  return "action";
};

const reviewTitle = (kind, operation, toolName) => {
  const subject = toolName || labelForKey(String(operation).split(".", 1)[0]);
  return {
    email: "Review the email before sending",
    presentation: "Review the presentation before creating it",
    ticket: "Review the ticket before creating or changing it",
    message: "Review the message before sending",
    calendar: "Review the calendar event before creating it",
    document: "Review the document before creating or changing it",
    records: `Review the ${subject} records before changing them`,
    content: `Review the ${subject} content before publishing`,
    design: "Review the Canva action before creating it",
    action: `Review the ${subject} action before running it`,
  }[kind];
};

export const fallbackReviewContract = (operation, args = {}, toolName = "App") => {
  const kind = reviewKindForOperation(operation);
  return {
    version: 1,
    kind,
    operation,
    title: operation === "jira.issues.create_from_blocks"
      ? "Review Jira tasks before creating them"
      : reviewTitle(kind, operation, toolName),
    description: "Review the exact values AURA will submit.",
    fields: Object.entries(args).map(([key, value]) => ({
      key,
      path: [key],
      label: labelForKey(key),
      type: Array.isArray(value) ? "array" : typeof value === "object" && value !== null ? "object" : typeof value,
      control: controlForValue(value),
      required: false,
      editable: true,
    })),
    editable_paths: Object.keys(args).map((key) => [key]),
  };
};

const previewForArguments = (contract, args, prepared = false) => {
  if (contract.kind === "email") {
    return {
      type: "email",
      to: args.to || "",
      subject: args.subject || "AURA workflow",
      body: args.body || "",
      note: prepared ? "Prepared from the completed workflow steps." : "Exact message from the saved plan.",
    };
  }
  if (contract.operation === "jira.issues.create_from_blocks") {
    return { type: "jira_batch", title: "Review Jira tasks before creating them" };
  }
  if (contract.kind === "ticket") {
    return {
      type: "jira",
      title: contract.title,
      project: args.project_key || args.projectKey || args.project || "",
      summary: args.summary || "",
      description: args.description || "",
      assignee: args.assignee_id || args.assignee || "",
    };
  }
  if (contract.kind === "document") {
    const content = args.body ?? args.content ?? args.description ?? args.children ?? "";
    return {
      type: "document",
      title: contract.title,
      docTitle: args.title || args.name || args.summary || "Untitled document",
      docBody: typeof content === "string" ? content : JSON.stringify(content, null, 2),
    };
  }
  return { type: contract.kind, title: contract.title };
};

export const plannedApprovalStep = (planned, runtime, toolName = "App") => {
  const args = runtime?.arguments && typeof runtime.arguments === "object"
    ? runtime.arguments
    : {};
  const base = {
    ...planned,
    operation: runtime?.operation || planned?.operation,
    arguments: args,
    resolvedArguments: args,
  };
  if (!runtime?.consequential) return base;
  const contract = fallbackReviewContract(base.operation, args, toolName);
  return {
    ...base,
    riskLevel: "modify",
    reviewContract: contract,
    preview: previewForArguments(contract, args),
  };
};

export const requiresActionPreview = (steps = [], autoApprove = false) => (
  !autoApprove && steps.some((step) => step?.riskLevel === "modify")
);

// The proposed Jira batch depends on Notion reads. Its first meaningful
// approval screen is the one containing the actual task titles.
// Reads and earlier writes must finish before their dependent actions have
// concrete arguments. Keep their exact approval for the execution boundary.
export const requiresPreparedActionReview = (step = {}) => (
  step.operation === "jira.issues.create_from_blocks"
  || (step.depends_on || []).length > 0
  || JSON.stringify(step.arguments || {}).includes("{{")
  || ["body", "content", "text", "message", "description"].some((field) => (
    /\b(?:will be|to be) (?:generated|written|drafted|filled|summarized)\b|\bplaceholder\b|\btbd\b/i.test(step.arguments?.[field] || "")
  ))
);

export const requiresPreparedJiraReview = (steps = []) => steps.some(
  (step) => step?.operation === "jira.issues.create_from_blocks",
);

export const hasImmediateActionPreview = (steps = [], autoApprove = false) => (
  requiresActionPreview(steps, autoApprove)
  && steps.some((step) => step?.riskLevel === "modify" && !requiresPreparedActionReview(step))
);

export const resolvedApprovalStep = (planned, runtime, toolName = "App") => {
  if (!runtime?.consequential) {
    if (runtime?.operation === "canva.export.create") {
      return { ...planned, riskLevel: "read", preview: undefined, approvalPending: false };
    }
    return planned;
  }
  if (runtime.approval_status !== "pending" || runtime.approval_preview?.status !== "ready") {
    return { ...planned, riskLevel: "read", preview: undefined, approvalPending: true };
  }
  const args = runtime.approval_preview.arguments || {};
  const reviewContract = runtime.approval_preview.review_contract
    || fallbackReviewContract(runtime.operation, args, toolName);
  return {
    ...planned,
    riskLevel: "modify",
    arguments: args,
    resolvedArguments: args,
    reviewContract,
    approvalId: runtime.approval_id,
    preview: previewForArguments(reviewContract, args, true),
  };
};

export const editedArgumentsForStep = (step = {}) => (
  step.resolvedArguments || step.arguments || step.preview?.arguments || {}
);

export const mergeLegacyPreviewIntoArguments = (step, preview) => {
  const args = { ...(step.resolvedArguments || step.arguments || {}) };
  if (preview?.type === "email") {
    return { ...args, to: preview.to, subject: preview.subject, body: preview.body };
  }
  if (preview?.type === "jira") {
    return {
      ...args,
      project_key: preview.project,
      summary: preview.summary,
      description: preview.description,
      assignee_id: preview.assignee,
    };
  }
  if (preview?.type === "document") {
    const titleKey = Object.hasOwn(args, "title") ? "title" : "name";
    const bodyKey = Object.hasOwn(args, "body") ? "body" : Object.hasOwn(args, "content") ? "content" : "description";
    return { ...args, [titleKey]: preview.docTitle, [bodyKey]: preview.docBody };
  }
  return args;
};

export const setArgumentAtPath = (argumentsValue, path, value) => {
  const next = structuredClone(argumentsValue || {});
  let target = next;
  path.slice(0, -1).forEach((segment) => {
    if (!target[segment] || typeof target[segment] !== "object") target[segment] = {};
    target = target[segment];
  });
  target[path[path.length - 1]] = value;
  return next;
};

const validateSchemaValue = (value, schema, path, errors, required = false) => {
  if (value == null) {
    if (required) errors.push({ path, message: "This value is required." });
    return;
  }
  if (value === "" && required) {
    errors.push({ path, message: "This value is required." });
    return;
  }
  if (value === "" && !(schema.minLength > 0)) return;
  const type = schema.type;
  if (type === "string") {
    if (typeof value !== "string") errors.push({ path, message: "Enter text." });
    else if (schema.minLength != null && value.length < schema.minLength) errors.push({ path, message: `Use at least ${schema.minLength} characters.` });
    else if (schema.maxLength != null && value.length > schema.maxLength) errors.push({ path, message: `Use no more than ${schema.maxLength} characters.` });
    else if (schema.format === "email" && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) errors.push({ path, message: "Enter a valid email address." });
    else if (schema.pattern) {
      try {
        if (!new RegExp(schema.pattern).test(value)) errors.push({ path, message: "Use the required format." });
      } catch {
        // The backend remains authoritative when an external manifest uses a non-JavaScript regex.
      }
    }
  } else if (type === "array") {
    if (!Array.isArray(value)) errors.push({ path, message: "Use a list of values." });
    else {
      if (schema.minItems != null && value.length < schema.minItems) errors.push({ path, message: `Add at least ${schema.minItems} item.` });
      if (schema.maxItems != null && value.length > schema.maxItems) errors.push({ path, message: `Use no more than ${schema.maxItems} items.` });
      value.forEach((item, index) => validateSchemaValue(item, schema.items || {}, [...path, index], errors));
    }
  } else if (type === "object") {
    if (!value || typeof value !== "object" || Array.isArray(value)) errors.push({ path, message: "Use structured values." });
    else {
      const objectRequired = new Set(schema.required || []);
      Object.entries(schema.properties || {}).forEach(([key, childSchema]) => {
        validateSchemaValue(value[key], childSchema || {}, [...path, key], errors, objectRequired.has(key));
      });
    }
  } else if (type === "boolean" && typeof value !== "boolean") {
    errors.push({ path, message: "Choose enabled or disabled." });
  } else if (type === "integer" && !Number.isInteger(value)) {
    errors.push({ path, message: "Enter a whole number." });
  } else if (type === "number" && typeof value !== "number") {
    errors.push({ path, message: "Enter a number." });
  }
  if (typeof value === "number" && schema.minimum != null && value < schema.minimum) errors.push({ path, message: `Use ${schema.minimum} or more.` });
  if (typeof value === "number" && schema.maximum != null && value > schema.maximum) errors.push({ path, message: `Use ${schema.maximum} or less.` });
  if (schema.enum && !schema.enum.includes(value)) errors.push({ path, message: "Choose one of the available values." });
};

export const validateReviewArguments = (contract = {}, args = {}) => {
  const errors = [];
  (contract.fields || []).forEach((field) => {
    const schema = {
      type: field.type,
      format: field.format,
      enum: field.options,
      minLength: field.min_length,
      maxLength: field.max_length,
      minItems: field.min_items,
      maxItems: field.max_items,
      minimum: field.minimum,
      maximum: field.maximum,
      pattern: field.pattern,
      items: field.item_schema,
      properties: field.properties,
    };
    validateSchemaValue(args[field.key], schema, field.path || [field.key], errors, field.required);
  });
  return errors;
};
