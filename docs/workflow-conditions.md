# Workflow conditions and variables

AURA workflow plans form a forward-only dependency graph. Each step has a stable `key`, may
depend on earlier steps, and may contain a structured condition. Provider output is available to
later steps under `steps.<key>`.

```json
{
  "key": "notify_sales",
  "depends_on": ["find_order"],
  "condition": {
    "left": "{{steps.find_order.total}}",
    "operator": "greater_than_or_equal",
    "right": "{{vars.high_value_threshold}}"
  },
  "tool_slug": "slack",
  "operation": "send_message",
  "arguments": {
    "channel": "{{vars.sales_channel}}",
    "text": "High-value order: {{steps.find_order.id}}"
  }
}
```

References support three namespaces:

- `inputs.*`: values supplied when the run starts.
- `vars.*`: reusable workflow defaults plus values saved by completed steps.
- `steps.<key>.*`: accepted provider output from an earlier step.

An exact reference preserves its native JSON type. A reference embedded in a longer string is
rendered as text. Missing values stop the run before the next provider action and create an audit
event.

To save output for reuse, define `output_variables` on a step:

```json
{
  "output_variables": {
    "customer_email": "{{steps.find_customer.email}}"
  }
}
```

Conditions are data, not executable source code. Supported operators are equality, ordered
comparison, containment, existence, and boolean checks. Dependencies must point to earlier steps,
which prevents cycles. A normal branch uses `all_succeeded`; a join after alternative branches uses
`all_settled`.
