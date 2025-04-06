# Chat App Project

This document outlines the initial technical preferences and MVP scope for building this chat application.

## Core Technical Choices

- **Frontend:** Plain HTML and JavaScript.
  - Adherence to hypermedia principles.
  - Potential future enhancements with HTMX and Alpine.js, but prioritize simplicity initially.
- **Backend:** Python.
- **Database:** SQLite.
- **Real-time Updates:** Server-Sent Events (SSE).
- **Development Process:** Test-Driven Development (TDD).

## MVP Scope

### User Stories

**1. Initiate a New Conversation**

- **As an** authenticated user,
- **I want to** select another _online_ user and send them an initial message,
- **So that** a new conversation is created between us, and they receive an invitation to join.
- **Acceptance Criteria:**
  - Given User A is authenticated and User B is online, when User A submits a request to start a conversation with User B including an initial message:
  - A new `Conversation` record is created, linked to User A (`created_by`).
  - A new `Message` record is created with User A's initial message, linked to the new conversation and User A.
  - A `Participant` record is created for User A, linked to the new conversation, with `status='joined'` and `joined_at` set.
  - A `Participant` record is created for User B, linked to the new conversation, with `status='invited'`, `invited_by_user_id=UserA.id`, and `initial_message_id` linking to the first message.
  - User B should _not_ yet receive real-time updates for this conversation.
  - If User B is _not_ online, the request fails with an appropriate error message, and no records are created.
  - If User B does not exist, the request fails.

**2. View and Respond to Invitations**

- **As an** authenticated user,
- **I want to** see a list of conversations I've been invited to, including who invited me and a preview of the first message,
- **So that** I can decide whether to accept or reject the invitation.
- **Acceptance Criteria:**
  - Given User B has a `Participant` record with `status='invited'`, when User B requests their list of invitations:
  - The response includes details for each invitation: inviting user's username, conversation ID, and the content of the message linked by `initial_message_id`.
  - When User B accepts an invitation:
    - The corresponding `Participant` record's `status` is updated to `'joined'`.
    - The `joined_at` timestamp is set.
    - User B starts receiving real-time updates for the conversation.
  - When User B rejects an invitation:
    - The corresponding `Participant` record's `status` is updated to `'rejected'`.
    - User B does _not_ receive real-time updates.

**3. Access Control for Invited Users**

- **As an** invited user (status='invited'),
- **I want** my access to the conversation to be restricted,
- **So that** I cannot participate until I explicitly accept the invitation.
- **Acceptance Criteria:**
  - Given User B has a `Participant` record with `status='invited'` for Conversation C:
  - User B cannot fetch the message history for Conversation C (API returns error/empty).
  - User B cannot send messages to Conversation C (API returns error).
  - User B does not receive SSE updates for new messages in Conversation C.

**4. Access Control for Joined Users**

- **As a** joined user (status='joined'),
- **I want** full access to the conversation,
- **So that** I can read history, send messages, and receive real-time updates.
- **Acceptance Criteria:**
  - Given User A has a `Participant` record with `status='joined'` for Conversation C:
  - User A can fetch the full message history for Conversation C.
  - User A can successfully send new messages to Conversation C.
  - New messages sent by other joined participants in Conversation C are delivered to User A via SSE.

**5. Invite User to an Existing Conversation**

- **As a** joined user (status='joined'),
- **I want to** invite another _online_ user to a conversation I'm part of,
- **So that** they can join our ongoing discussion.
- **Acceptance Criteria:**
  - Given User A is 'joined' in Conversation C, and User C is online but not yet a participant:
  - When User A submits a request to invite User C to Conversation C:
  - A new `Participant` record is created for User C, linked to Conversation C, with `status='invited'` and `invited_by_user_id=UserA.id`. The `initial_message_id` can be null in this case.
  - User C receives the invitation (as per Story 2 requirements).
  - If User C is _not_ online, the request fails.
  - If User C is already a participant (status != 'rejected' or 'left'), the request fails.
  - If User A is _not_ 'joined' in Conversation C, the request fails.

### Authentication

- **Initial Approach:** Simple "anonymous auth" where a user is identified solely by a transient session token stored client-side (e.g., in cookies or local storage).
- **Data Persistence:** Loss of the session token (e.g., clearing cookies/storage) results in permanent loss of that specific user identity and associated conversation access.
- **Future Enhancement:** Persistent authentication methods (e.g., username/password, OAuth) can be added later as an _option_ for users who wish to retain their identity across sessions.

## Data Model

The following describes the conceptual structure of the database tables using SQLite. Timestamps (`created_at`, `updated_at`) are standard datetime fields. IDs (`_id`) are UUIDs, prefixed according to the table. Foreign Keys are denoted by `FK`.

**`User`**

- `_id` (PK, prefixed uuid: 'user\_')
- `username` (string, unique, not null): Auto-generated unique name (e.g., `witty-walrus`, format: `lowercase-adjective-noun`).
- `created_at`
- `updated_at`
- `deleted_at` (nullable)
- `is_online` (boolean, default: false): Indicates if the user is currently connected/active.

**`Conversation`**

- `_id` (PK, prefixed uuid: 'conv\_')
- `name` (string, nullable): Optional display name for the conversation.
- `created_by` (FK to `User._id`, not null): User who initiated the conversation.
- `created_at`
- `updated_at`
- `deleted_at` (nullable)

**`Message`**

- `_id` (PK, prefixed uuid: 'msg\_')
- `content` (string, not null)
- `conversation_id` (FK to `Conversation._id`, not null)
- `created_by` (FK to `User._id`, not null): User who sent the message.
- `created_at`

**`Participant`** (Replaces `ConversationMembership` and `JoinRequest`)

- `_id` (PK, prefixed uuid: 'part\_')
- `user_id` (FK to `User._id`, not null)
- `conversation_id` (FK to `Conversation._id`, not null)
- `status` (string, not null, options: 'invited', 'joined', 'rejected', 'left')
- `invited_by_user_id` (FK to `User._id`, nullable): User who sent the invitation, if status is 'invited'.
- `initial_message_id` (FK to `Message._id`, nullable): The first message sent, used for preview in invitations.
- `created_at`: Timestamp when the participation record was created (e.g., invite sent, creator joined).
- `updated_at`: Timestamp when status or other fields last changed.
- `joined_at` (timestamp, nullable): Timestamp when the status became 'joined'.
- _Constraint:_ Unique index on (`user_id`, `conversation_id`).
