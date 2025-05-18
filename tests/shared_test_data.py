from pydantic import BaseModel
import urllib.parse

# Common data for creating conversations
TEST_INVITEE_USERNAME = "shared_testuser"
TEST_INITIAL_MESSAGE = "Hello from shared data!"


# Pydantic model for API tests (can also be used to generate form data)
class ConversationCreateRequestData(BaseModel):
    invitee_username: str = TEST_INVITEE_USERNAME
    initial_message: str = TEST_INITIAL_MESSAGE


# Helper to get form-encoded string for contract tests
def get_form_encoded_creation_data() -> str:
    # Instantiate the model to get default values or pass specific values if needed
    request_data_model = ConversationCreateRequestData()
    data = request_data_model.model_dump()
    return urllib.parse.urlencode(data)
