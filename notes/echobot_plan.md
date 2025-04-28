# Echobot Implementation Plan

## Purpose

To facilitate easier manual and potentially automated testing of conversation features by providing a predictable participant (`echobot`) that can always be invited and interacts in a simple, deterministic way.

## Requirements

1.  **Always Exists:** An `echobot` `User` record should exist in the database, potentially created via a seed script or migration.
2.  **Always Online:** The `echobot` user should always have `is_online=True`.
3.  **Auto-Join:** When `echobot` receives a conversation invitation (`Participant` status becomes `invited`), the system should automatically transition its status to `joined`.
    - This could be triggered by a database trigger, a background task monitoring invitations, or logic within the invitation endpoint itself (if feasible without overcomplicating).
4.  **Echo Messages:** When a message is sent to a conversation where `echobot` is a `joined` participant, `echobot` should automatically send a new message to the same conversation, echoing the content of the message it just "received".
    - Example: If User A sends "Hello there", `echobot` sends "Echo: Hello there".
    - This requires monitoring new messages (perhaps via SSE internally or another mechanism) and triggering a response. Care must be taken to avoid infinite loops if two echobots were in a conversation (e.g., by ignoring messages sent _by_ `echobot`).
5.  **Distinct Username:** The username should clearly identify it, e.g., `echobot`.

## Implementation Considerations

- **Seeding:** How will the initial `echobot` user be created reliably in different environments (dev, test, prod)? A data migration using Alembic is a good option.
- **Auto-Join Mechanism:** A background task or modifying the participant update logic seems most robust. Directly adding logic to the invite endpoint might tightly couple concerns.
- **Echo Mechanism:** This is the most complex part. It needs to react to _other_ users' messages.
  - Could leverage the same SSE mechanism used for clients.
  - Could use database triggers (though complex logic in triggers is often discouraged).
  - Could be a separate background process polling for new messages in conversations involving `echobot`.
- **Authentication:** `echobot` shouldn't need to "log in". Its actions will be triggered server-side.

## Benefits

- **Manual Testing:** Easily start conversations without needing multiple browser sessions or user accounts.
- **Automated Testing:** Can be used in integration or end-to-end tests to verify message sending, receiving, and participant status changes.
- **Demo:** Useful for demonstrating conversation functionality.
