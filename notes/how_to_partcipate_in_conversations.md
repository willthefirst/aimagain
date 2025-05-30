# How to participate in conversations

## Overview

This document describes the typical flow for creating, joining, and participating in conversations in our chat application using the web interface.

## Conversation participation flow

```mermaid
sequenceDiagram
    actor User1 as User (Initiator)
    participant Browser as Web Browser
    participant API as Server/API
    actor User2 as User (Invitee)
    actor User3 as User (Another User)

    %% Initiate Conversation Flow %%
    User1->>Browser: Clicks "Create New Conversation" link (on /conversations)
    Browser->>API: GET /conversations/new
    API-->>Browser: HTML form for new conversation

    User1->>Browser: Enters User2's username, initial message, Submits form
    Browser->>API: POST /conversations (Content-Type: form-urlencoded)
    Note right of API: Find User2 by username,<br/>Create Conversation,<br/>Create initial Message,<br/>Create Participant (User1, status=JOINED),<br/>Create Participant (User2, status=INVITED)
    API-->>Browser: Redirect to /conversations/{new_slug}

    Browser->>API: GET /conversations/{new_slug}
    API-->>Browser: HTML detail page for the new conversation (User1 sees the chat)
    Note over Browser,API: User1 is now in the conversation view

    API->>User2: Notify about invitation (e.g., update User2's UI)

    %% User2 Joins %%
    User2->>Browser: Views invitation, Accepts
    Browser->>API: PUT /participants/{participant_id_user2} (status=JOINED)
    Note right of API: Update Participant status from INVITED to JOINED
    API-->>Browser: Return updated Participant details (or success confirmation)
    Note over Browser,API: User2 can now fully participate

    %% Inviting Another User (User3) %%
    User1->>Browser: Uses UI element to invite User3 (on /conversations/{slug} page)
    Browser->>API: POST /conversations/{slug}/participants (invitee_user_id=User3.id)
    Note right of API: Create Participant (User3, status=INVITED)
    API-->>Browser: Return updated Conversation/Participant info
    API->>User3: Notify about invitation

    %% Messaging %%
    User2->>Browser: Sends message
    Browser->>API: POST /conversations/{slug}/messages (content=...)
    API-->>Browser: Return Message acknowledgment
    API->>User1: Deliver message via SSE

    User1->>Browser: Sends reply
    Browser->>API: POST /conversations/{slug}/messages (content=...)
    API-->>Browser: Return Message acknowledgment
    API->>User2: Deliver message via SSE
```

## How it works

1.  **Initiating a Conversation (UI Flow)**:

    - A user clicks "Create New Conversation" (typically on the `/conversations` list page).
    - They are directed to the `/conversations/new` page, which displays a form.
    - The user enters the `username` of the desired _online_ participant and an initial message, then submits the form.
    - The browser sends a `POST` request to `/conversations` with the form data.
    - The backend API finds the invitee user by username, creates the `Conversation`, the initial `Message`, adds the initiator as a `Participant` with `status='joined'`, and adds the invitee as a `Participant` with `status='invited'`.
    - The API responds with a redirect to the new conversation's page (`/conversations/{slug}`).
    - The initiator's browser follows the redirect and loads the conversation detail page.

2.  **Inviting Additional Participants**: Once a conversation exists, any participant who has `JOINED` can invite other _online_ users. This is typically done via UI elements on the conversation page which trigger a `POST` request to `/conversations/{slug}/participants` containing the `invitee_user_id`. These new participants are initially marked with an `INVITED` status.

3.  **Joining a Conversation**: When invited (either initially or subsequently), a user sees the invitation (e.g., in their `/users/me/invitations` list or via a notification). They can accept it, typically by triggering a `PUT` request to `/participants/{participant_id}` with `status='joined'`. This updates their status and grants them full access.

4.  **Messaging**: Only participants with `JOINED` status can send messages (typically via a form `POST` to `/conversations/{slug}/messages`) and receive real-time updates (via SSE) for the conversation.

5.  **Leaving or Rejecting**:
    - An invited user can reject an invitation by updating their participant status to `REJECTED` (e.g., `PUT /participants/{participant_id}` with `status='rejected'`).
    - A joined user can leave by updating their status to `LEFT`.

## Important note

**Only participants with a `JOINED` status can invite _additional_ users to an existing conversation (via `POST /conversations/{slug}/participants`).** The initial creation `POST /conversations` handles the first invitation implicitly based on the submitted username.
