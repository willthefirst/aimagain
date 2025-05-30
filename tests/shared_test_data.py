import urllib.parse

from pydantic import BaseModel

from tests.test_contract.constants import (
    TEST_INITIAL_MESSAGE,
    TEST_INVITEE_USERNAME,
    TEST_MESSAGE_CONTENT,
)


class ConversationCreateRequestData(BaseModel):
    invitee_username: str = TEST_INVITEE_USERNAME
    initial_message: str = TEST_INITIAL_MESSAGE


class MessageCreateRequestData(BaseModel):
    message_content: str = TEST_MESSAGE_CONTENT


def get_form_encoded_creation_data() -> str:
    request_data_model = ConversationCreateRequestData()
    data = request_data_model.model_dump()
    return urllib.parse.urlencode(data)


def get_form_encoded_message_data() -> str:
    request_data_model = MessageCreateRequestData()
    data = request_data_model.model_dump()
    return urllib.parse.urlencode(data)
