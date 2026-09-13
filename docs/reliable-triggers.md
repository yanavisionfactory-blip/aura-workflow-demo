# Reliable triggers

## Webhooks

Every incoming webhook must include a stable event ID, Unix timestamp, and HMAC signature over
`timestamp + "." + raw_body`. Requests outside the five-minute window are rejected.

A subscription and event ID pair is unique. Identical retries receive the existing delivery and
run identifiers without creating another run. Reusing the same event ID with different content is
rejected as a collision. The unique delivery is claimed before its run is created, closing the
concurrent-delivery race.

Administrators can replay a delivery only when its original run failed before any action completed.
Each replay creates a new delivery and run linked to the original, and the operator must provide an
audit reason.

## Polling

Polling subscriptions can configure a response `checkpoint_path` and matching request
`cursor_argument`. For example, `next_cursor` can be copied into `page.cursor` on the following
request.

The subscription row is locked while a poll is processed. Its payload fingerprint, checkpoint,
delivery, generated run, and audit event commit in one transaction. A crash before commit leaves
the previous checkpoint intact, so the same page can be fetched safely. A unique payload hash
prevents the refetched page from creating a duplicate run.
