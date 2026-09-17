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

export const fallbackReviewContract = (operation, args = {}, toolName = "App") => ({
  version: 1,
  kind: "action",
  operation,
  title: `Review the ${toolName} action before running it`,
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
});

const previewForArguments = (contract, args) => {
  if (contract.kind === "email") {
    return {
      type: "email",
      to: args.to || "",
      subject: args.subject || "",
      body: args.body || "",
      note: "Prepared from the completed workflow steps.",
    };
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
  return { type: contract.kind, title: contract.title };
};

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
    preview: previewForArguments(reviewContract, args),
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
