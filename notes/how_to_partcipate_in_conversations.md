# How to Participate in Conversations

## Overview

This document describes the flow for creating and joining conversations in our chat application.

## Conversation Participation Flow

```mermaid
sequenceDiagram
    actor User1 as User (Creator)
    participant API as Server/API
    actor User2 as Other User

    User1->>API: POST /conversations (Create new conversation)
    API-->>User1: Return Conversation with User1 as Participant (status=JOINED)

    User1->>API: POST /conversations/{slug}/participants (Invite User2)
    Note right of API: Create Participant with status=INVITED
    API-->>User1: Return updated Conversation

    API->>User2: Notify about invitation

    User2->>API: PUT /conversations/{slug}/participants/{id} (Update status to JOINED)
    Note right of API: Update Participant status from INVITED to JOINED
    API-->>User2: Return updated Participant

    User2->>API: POST /conversations/{slug}/messages (Send message)
    API-->>User2: Return Message acknowledgment
    API->>User1: Deliver message to User1

    User1->>API: POST /conversations/{slug}/messages (Reply)
    API-->>User1: Return Message acknowledgment
    API->>User2: Deliver message to User2
```

## How It Works

1. **Creating a Conversation**: A user creates a new conversation by sending a POST request to `/conversations`. The system automatically adds the creator as a participant with a `JOINED` status.

2. **Inviting Participants**: The conversation creator (or any participant with `JOINED` status) can invite other users by sending a POST request to `/conversations/{slug}/participants`. These new participants are initially marked with an `INVITED` status.

3. **Joining a Conversation**: When invited, a user can accept the invitation by updating their participant status from `INVITED` to `JOINED` using a PUT request to `/conversations/{slug}/participants/{id}`.

4. **Messaging**: Only participants with `JOINED` status can send and receive messages in the conversation.

5. **Leaving or Rejecting**: Participants can update their status to `LEFT` to leave a conversation, or `REJECTED` if they decline an invitation.

## Important Note

**Only participants with a `JOINED` status can invite other users to a conversation.** This ensures that conversation membership is controlled by active participants.
