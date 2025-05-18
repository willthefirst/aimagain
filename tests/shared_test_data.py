import urllib.parse

from pydantic import BaseModel

TEST_INVITEE_USERNAME = "shared_testuser"
TEST_INITIAL_MESSAGE = "Hello from shared data!"


class ConversationCreateRequestData(BaseModel):
    invitee_username: str = TEST_INVITEE_USERNAME
    initial_message: str = TEST_INITIAL_MESSAGE


def get_form_encoded_creation_data() -> str:
    request_data_model = ConversationCreateRequestData()
    data = request_data_model.model_dump()
    return urllib.parse.urlencode(data)
