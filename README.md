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
- **I want to** `POST` to `/conversations`, providing the target _online_ user's ID and an initial message,
- **So that** a new conversation is created between us, and they receive an invitation to join.
- **Acceptance Criteria:**
  - Given User A is authenticated and User B is online, when User A `POST /conversations` with `{ "invitee_user_id": "user_...", "initial_message": "..." }` in body:
  - A new `Conversation` record is created, linked to User A (`created_by`), including a unique `slug` and `last_activity_at` timestamp.
  - A new `Message` record is created with User A's initial message, linked to the new conversation and User A.
  - A `Participant` record is created for User A, linked to the new conversation, with `status='joined'` and `joined_at` set.
  - A `Participant` record is created for User B, linked to the new conversation, with `status='invited'`, `invited_by_user_id=UserA.id`, and `initial_message_id` linking to the first message.
  - User B should _not_ yet receive real-time updates for this conversation.
  - If User B is _not_ online, the request fails with an appropriate error message (e.g., 400 Bad Request), and no records are created.
  - If User B does not exist, the request fails (e.g., 404 Not Found).
  - The `Conversation.last_activity_at` timestamp is updated.

**2. View and Respond to Invitations**

- **As an** authenticated user,
- **I want to** `GET /users/me/invitations` to see my pending invitations, including who invited me and a preview of the first message,
- **So that** I can decide whether to accept or reject the invitation.
- **Acceptance Criteria:**
  - Given User B has a `Participant` record (`_id=part_xyz`) with `status='invited'`, when User B `GET /users/me/invitations`:
  - The response includes details for each invitation: `participant_id` (`part_xyz`), inviting user's username, conversation `slug`, and the content of the message linked by `initial_message_id`.
  - When User B accepts an invitation by sending a `PUT /participants/part_xyz` request with `{ "status": "joined" }`:
    - The corresponding `Participant` record's `status` is updated to `'joined'`.
    - The `joined_at` timestamp is set.
    - User B starts receiving real-time updates for the conversation.
    - The `Conversation.last_activity_at` timestamp is updated.
  - When User B rejects an invitation by sending a `PUT /participants/part_xyz` request with `{ "status": "rejected" }`:
    - The corresponding `Participant` record's `status` is updated to `'rejected'`.
    - User B does _not_ receive real-time updates.
    - The `Conversation.last_activity_at` timestamp is updated.

**3. Access Control for Invited Users**

- **As an** invited user (status='invited'),
- **I want** my access to the conversation to be restricted,
- **So that** I cannot participate until I explicitly accept the invitation.
- **Acceptance Criteria:**
  - Given User B has a `Participant` record with `status='invited'` for Conversation C (slug `conv-slug`):
  - User B cannot `GET /conversations/conv-slug` (API returns 403 Forbidden).
  - User B cannot fetch the message history for Conversation C (e.g., `GET /conversations/conv-slug/messages` returns 403).
  - User B cannot send messages to Conversation C (e.g., `POST /conversations/conv-slug/messages` returns 403).
  - User B does not receive SSE updates for new messages in Conversation C.

**4. Access Control for Joined Users**

- **As a** joined user (status='joined'),
- **I want** full access to the conversation,
- **So that** I can read history, send messages, and receive real-time updates.
- **Acceptance Criteria:**
  - Given User A has a `Participant` record with `status='joined'` for Conversation C (slug `conv-slug`):
  - User A can `GET /conversations/conv-slug` to retrieve conversation details.
  - User A can fetch the full message history for Conversation C (e.g., `GET /conversations/conv-slug/messages`, possibly with pagination).
  - User A can successfully send new messages to Conversation C (e.g., `POST /conversations/conv-slug/messages`).
  - The `Conversation.last_activity_at` timestamp is updated upon sending a message.
  - New messages sent by other joined participants in Conversation C are delivered to User A via SSE.

**5. Invite User to an Existing Conversation**

- **As a** joined user (status='joined'),
- **I want to** `POST` to `/conversations/{slug}/participants`, providing the target _online_ user's ID,
- **So that** they receive an invitation to join the conversation.
- **Acceptance Criteria:**
  - Given User A is 'joined' in Conversation C (with `slug=conv-slug`), and User B is online but not yet a participant:
  - When User A `POST /conversations/conv-slug/participants` with `{ "invitee_user_id": "user_..." }`:
  - A new `Participant` record is created for User B, linked to Conversation C, with `status='invited'` and `invited_by_user_id=UserA.id`. `initial_message_id` can be null.
  - User B receives the invitation (as per Story 2 requirements).
  - The `Conversation.last_activity_at` timestamp is updated.
  - If User B is _not_ online, the request fails (e.g., 400 Bad Request).
  - If User B is already a participant (status is 'invited' or 'joined'), the request fails (e.g., 409 Conflict).
  - If User A is _not_ 'joined' in Conversation C, the request fails (e.g., 403 Forbidden).

**6. List All Public Conversations**

- **As any** user (authenticated or not),
- **I want to** `GET /conversations`,
- **So that** I can see a list of all active conversations on the platform.
- **Acceptance Criteria:**
  - The response is a list of conversation summaries.
  - Each summary includes: `slug`, `name` (if any), list of participant `username`s (only those 'joined'), and `last_activity_at`.
  - The list should be sortable by `last_activity_at` (descending by default).
  - Private/internal `_id`s are not exposed.

**7. List My Conversations**

- **As an** authenticated user,
- **I want to** `GET /users/me/conversations`,
- **So that** I can see all conversations I am currently part of ('joined' or 'invited').
- **Acceptance Criteria:**
  - The response lists conversations where the authenticated user has a `Participant` record with status 'joined' or 'invited'.
  - Each item includes: `slug`, `name`, participant usernames (all statuses?), `last_activity_at`, and the user's own `status` ('joined' or 'invited').
  - The list should be sortable by `last_activity_at` (descending by default).

**8. View a Specific Conversation**

- **As an** authenticated user,
- **I want to** `GET /conversations/{slug}`,
- **So that** I can view the details and message history of a conversation I have joined.
- **Acceptance Criteria:**
  - Given User A `GET /conversations/conv-slug`:
  - If User A has a `Participant` record for this conversation with `status='joined'`, the response includes conversation details (`slug`, `name`, participant list with usernames and status) and its recent message history (e.g., last 50 messages, with pagination options).
  - If User A is 'invited' or not a participant, the API returns 403 Forbidden.

**9. List All Users (In Progress)**

- **As any** user (authenticated or not),
- **I want to** `GET /users`,
- **So that** I can see a list of all registered users on the platform.
- **Acceptance Criteria:**
  - The response is a list of user summaries.
  - Each summary includes: `username`, `created_at`, and a calculated `last_activity_at` (timestamp of the user's last message or participation status change, whichever is latest).
  - The list should be sortable (e.g., by `username`, `last_activity_at`).
  - Internal `_id`s are not exposed.

**10. List Users I've Chatted With**

- **As an** authenticated user,
- **I want to** `GET /users?participated_with=me`,
- **So that** I can easily find users I share conversations with.
- **Acceptance Criteria:**
  - The response lists users who share at least one conversation where both the authenticated user and the listed user have status 'joined'.
  - Each user summary includes `username`, `created_at`, `last_activity_at`.

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
- `slug` (string, unique, not null): User-friendly unique identifier (e.g., `happy-dolphin-talk`).
- `created_by` (FK to `User._id`, not null): User who initiated the conversation.
- `created_at`
- `updated_at`
- `deleted_at` (nullable)
- `last_activity_at` (timestamp, nullable): Timestamp of the last meaningful activity (message, participant change).

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

## API Endpoints (RESTful)

- `POST /conversations`
  - Action: Initiate a new conversation by inviting a user.
  - Body: `{ "invitee_user_id": "user_...", "initial_message": "..." }`
  - Response: Details of the newly created conversation and participant records (or error).
- `GET /conversations`
  - Action: List public summaries of all conversations.
  - Response: `[ { slug, name, participants: [username], last_activity_at }, ... ]`
- `GET /conversations/{slug}`
  - Action: View details and recent messages of a _joined_ conversation.
  - Response: `{ slug, name, participants: [{username, status}], messages: [...], ... }` (Requires 'joined' status).
- `POST /conversations/{slug}/participants`
  - Action: Invite another user to an existing conversation.
  - Body: `{ "invitee_user_id": "user_..." }`
  - Response: Details of the new participant record (or error).
- `GET /users`
  - Action: List public summaries of all users.
  - Response: `[ { username, created_at, last_activity_at }, ... ]`
- `GET /users/me/conversations`
  - Action: List conversations the current user is part of (joined or invited).
  - Response: `[ { slug, name, participants: [username], last_activity_at, my_status }, ... ]`
- `GET /users/me/invitations`
  - Action: List pending conversation invitations for the current user.
  - Response: `[ { participant_id, inviting_user: {username}, conversation: {slug}, initial_message_preview }, ... ]`
- `PUT /participants/{participant_id}`
  - Action: Accept or reject a conversation invitation.
  - Body: `{ "status": "joined" | "rejected" }`
  - Response: Updated participant record details (or error).
- `GET /users?participated_with=me`
  - Action: List users the current authenticated user shares 'joined' conversations with.
  - Response: `[ { username, created_at, last_activity_at }, ... ]`

## Setup and Running

Follow these steps to set up the project locally:

1.  **Clone the Repository:**

    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```

2.  **Create and Activate Virtual Environment:**
    It's highly recommended to use a virtual environment.

    ```bash
    python -m venv venv  # Or use python3 if needed
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3.  **Install Dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

4.  **Set Up Environment Variables:**
    Copy the example environment file and customize if needed (though the defaults should work for basic setup).

    ```bash
    cp .env.example .env
    ```

    The `.env` file is ignored by git and contains environment-specific settings like database URLs. The application (`app/db.py`) and Alembic (`alembic/env.py`) are configured to read this file.

5.  **Apply Database Migrations:**
    This command creates the database file (e.g., `chat_app.db` specified in `.env`) and applies all schema migrations.

    ```bash
    alembic upgrade head
    ```

    If you make changes to the models in `app/models.py`, you'll need to generate a new migration:

    ```bash
    alembic revision --autogenerate -m "Your descriptive message"
    ```

    And then apply it:

    ```bash
    alembic upgrade head
    ```

6.  **Run the Development Server:**
    This starts the FastAPI application using the Uvicorn server.

    ```bash
    uvicorn app.main:app --reload
    ```

    The API will typically be available at `http://127.0.0.1:8000`. You can access the interactive API documentation (Swagger UI) at `http://127.0.0.1:8000/docs`.

7.  **Run Tests (Optional):**
    To run the test suite (once tests are added):
    ```bash
    pytest
    ```
