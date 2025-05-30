# Contract tests test the waiter, not the chef

## The restaurant analogy

This analogy helps clarify what contract tests should and shouldn't verify.

### Testing the waiter (Contract tests)

- Verifies the waiter can take orders correctly
- Ensures the waiter understands the menu
- Confirms the waiter writes down all required information
- Checks that the waiter follows the restaurant's ordering protocol
- Validates that the waiter can communicate with the kitchen

The waiter test doesn't care if the food is good - it only cares that the order is taken correctly. For example:

- If a customer orders "a burger with fries", the waiter test verifies that:
  - The order is written down correctly
  - All required fields are filled (burger type, doneness, etc.)
  - The order is formatted properly for the kitchen
  - The waiter knows how to handle special requests

### Testing the chef (Functional tests)

- Verifies the food is prepared correctly
- Ensures ingredients are fresh
- Confirms cooking temperatures are correct
- Checks that the meal matches the order
- Validates the final presentation

The chef test doesn't care about how the order was taken - it only cares that the food is prepared correctly. For example:

- If a customer orders "a burger with fries", the chef test verifies that:
  - The burger is cooked to the requested temperature
  - The fries are crispy
  - The ingredients are fresh
  - The meal is presented properly

Example 1: Ensuring POST /conversations success works

A functional test could prove that POST /conversations/ with format www-url-encoded creates a new Conversation.
But nothing yet proves that the CONSUMER sends that request correctly. For example, the client could submit the data as JSON rather than www-url-encoded, causing a 500.
We need something that shows that our client is communicating according the PROVIDER's spec.
So something that tests 'when a user tries to create a new Conversation, the client issues a request in the correct format.
We have that in the the form of a Consumer test, which runs a mock server that defines the form that it expects.
The task now is show that the PROVIDER "can handle" that request correctly.
Concretely, we need to send a request to the real PROVIDER in a PROVIDER test that matches the form that the Consumer has agreed to send along.
If the PROVIDER can handle the request (eg. properly handles www-url-encoded data), the test should pass.
If the PROVIDER cannot handle the request (eg. breaks when it receives JSON), the test should fail.
For this specific example, we could get away with mocking the entire PROVIDER handler, since we need to test the business logic that creates the user.
We really just need to see it barf on the wrong format.

So imagine, we get these tests to pass, and everything works:

- CONSUMER test proves that client sends correct format (www-url-encoded).
- PROVIDER test proves that the provider can handle that format.
- Functional test shows that the PROVIDER, upon receiving some request, actually has sufficient business logic.

But a wee later, the PROVIDER team decides that they don't want to use JSON instead of www-url-encoded.
If they go and change the actual provider code to now expect JSON rather than www-url-encoded,

- Their functional tests should break. So they go fix the functional tests, changing the test request format from www-url-encoded to JSON. Now the functional tests pass.
- Their contract tests should also break. The actual provider would have barfed on the wrong format, so they would have had to update the consumer to send the correct data,
  which would update the test run against the provider. Then everything would pass.

Conclusion: in this example, the contract tests would ensure that the CONSUMER must submit what the PROVIDER expects, and if the PROVIDER changes, it will force the CONSUMER to change too.

Example 2: Ensuring POST /conversations 'user not found' error works

A functional test proves that POST to /conversations with { ..., username: some-user-123, ...} for which we can't find the actual user with that username returns a 404 'user not found' error.
However, nothing proves that the CONSUMER sends the request correctly. For example, it could send POST data that doesn't contain the 'username' key/value, and is currently breaking on prod!
We need something that shows that the CONSUMER is communicating according to the PROVIDER's spec.
So something that tests 'when a user triest to create a new Conversation, the client issues a request in the correct format
We have that in the form of the Consumer test, which runs the mock server that defines the data format it expects.
The task now is show that the PROVIDER "can handle" that request correctly.
Concretely, we need to send a request to real PROVIDER in a PROVIDER test that matches the form that the Consumer has agreed to send along.
If the PROVIDER can't handle the request (eg. eventually tries to access an non-existent 'username' field in the request), it should fail.
Presummmably (almost certain): FastAPI validates the form of this kind of request with Pydantic, so we should get some kind of malformed response from FastAPI
before we even get into the handler code. So like in Example 1, this test could mock the entire handler function since the only thing the contract cares about is that
the messages being sent follows the contract. A contract test break until we get the consumer to expect the 'username' field, the actual client code to send it,
and then when we replay that request against the real provider in the provider test, the contract test will now pass.
Okay, now we've ensure that the Consumer and Provider agree on the shape of message to send. This still only confirms that the Consumer will send stuff in the correct shape,
but doesn't tell us that 'in this state X, response will be Y'. And again, we actually already test THAT side of things with our functional tests,
like we already have a test that says 'when a valid request gets sent in the 'non-existent user' application state, the response will be a 404.
So do we actually need to check anything else with this Contract test?
With the way this stuff works, the Provider test must be run against the Provider, and the Provider should reply with the expected response...
...so why not just entirely mock the handler response, and never run any business logic? This would accomplish the goal of just testing the message.

Would this test work 'keep us safe'? What future change could illustrate what the test protects against?
Certainly malformed data.
For example, what if the PROVIDER team decides they want to change the error code for 'missing user' from 404 to 403.

- The functional test would break, they'd have to update them to expect 404 rather than 403.
- The contract test wouldn't break...since the provider mocks the business logic entirely (and sends it's own 404),
  nothing would need to change, and yet, the application behavior would have drifted away from the tests. The CONSUMER test would expect a 404,
  the PROVIDER would confirm that a 404 is sent when it's actually not.
  I feel like our contract tests just shouldn't try to test 'state-specific' stuff. That's for the functional tests. The contract tests just ensure that client sends properly formatted messages.
- no missing fields
- proper encoding
- proper headers

The contract test really just tests 'the thing that comes from the consumer is in the right shape for the provider'. As far as what the provider then does, how it responds, that's beyond the scope of the contract test.,

## Key takeaways

1. **Separation of Concerns**

   - Contract tests verify interface compatibility
   - Functional tests verify behavior correctness

2. **Mocking Strategy**

   - Contract tests can mock business logic
   - Focus on message format and structure
   - Keep tests fast and focused

3. **Change Protection**

   - Contract tests protect against interface changes
   - Functional tests protect against behavior changes
   - Both are necessary for complete coverage

4. **Implementation Details**
   - Contract tests should be implementation-agnostic
   - Focus on the contract, not the implementation
   - Allow for implementation changes without breaking tests

## Conclusion

Contract tests and functional tests serve different but complementary purposes. Contract tests ensure that systems can communicate, while functional tests ensure they communicate correctly. By maintaining this separation, we can create more maintainable and reliable systems.
