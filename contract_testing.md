Let me create a comprehensive script that integrates FastAPI, Python, Playwright, and Pact-Python to test real HTML forms against your API contracts.

I've created a complete implementation for testing FastAPI forms with Playwright and Pact in Python. This script demonstrates how to verify that your actual HTML forms submit data in the format your API expects.

## Key Components of the Solution

1. **Test Environment Setup**:

   - A FastAPI server that serves your HTML pages for testing
   - Routes for both regular form submissions and file uploads
   - Static HTML files with the forms to be tested

2. **Pact Integration**:

   - Creates a Pact mock server to verify API contracts
   - Defines expected request/response patterns for form submissions
   - Verifies that actual form submissions match these expectations

3. **Playwright Testing**:

   - Launches a real browser to test the actual HTML forms
   - Uses request interception to redirect API calls to the Pact mock server
   - Fills and submits forms just like a real user would

4. **Complete Test Flow**:
   - Tests both regular forms (application/x-www-form-urlencoded) and file uploads (multipart/form-data)
   - Creates Pact contract files that your API can verify against
   - Provides end-to-end verification of your form submission process

## How To Use This Script

1. Install the required packages:

   ```bash
   pip install fastapi uvicorn pytest pytest-asyncio playwright pact-python
   ```

2. Initialize Playwright:

   ```bash
   playwright install
   ```

3. Run the script once to create the test HTML files:

   ```bash
   python test_profile_form.py
   ```

4. Run the tests:
   ```bash
   pytest -v test_profile_form.py
   ```

This approach gives you true confidence that your HTML forms work correctly with your FastAPI backend, bridging the gap between frontend and backend testing through Pact contract verification.

Would you like me to explain any specific part of the implementation in more detail or adapt it further to your specific needs?
