# test_profile_form.py
import asyncio
import os
import pytest
import uvicorn
from fastapi import FastAPI, Form, File, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pact import Consumer, Provider
from playwright.async_api import async_playwright
import threading
import time
import json
from typing import Optional

# ----- FastAPI Test Server Setup -----

# This is the FastAPI app that will serve your HTML pages for testing
app = FastAPI()

# Mount static files directory (this would contain your actual HTML pages)
app.mount("/static", StaticFiles(directory="static"), name="static")


# Simple endpoint to serve the form page
@app.get("/profile")
async def profile_page():
    with open("static/profile.html", "r") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content, status_code=200)


# This is the API endpoint that your form would normally submit to
# In our tests, we'll redirect this to the Pact mock server
@app.post("/api/profile")
async def update_profile(
    name: str = Form(...), email: str = Form(...), bio: Optional[str] = Form(None)
):
    # In a real app, this would update a database
    return JSONResponse(content={"success": True})


# File upload endpoint example
@app.post("/api/documents/upload")
async def upload_document(
    document: UploadFile = File(...), description: str = Form(...)
):
    # In a real app, this would save the file
    return JSONResponse(content={"fileId": f"doc-{int(time.time())}"})


# ----- Tests -----


@pytest.fixture(scope="module")
def fastapi_server():
    """Start FastAPI server as a background process for tests"""
    # Find an available port
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("localhost", 0))
    port = s.getsockname()[1]
    s.close()

    # Start FastAPI in a separate thread
    server_thread = threading.Thread(
        target=uvicorn.run,
        args=(app,),
        kwargs={"host": "localhost", "port": port, "log_level": "error"},
    )
    server_thread.daemon = True
    server_thread.start()

    # Give the server time to start
    time.sleep(1)

    yield f"http://localhost:{port}"


@pytest.fixture(scope="module")
async def browser():
    """Create a Playwright browser for testing"""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        yield browser
        await browser.close()


@pytest.fixture(scope="function")
async def page(browser):
    """Create a new page for each test"""
    page = await browser.new_page()
    yield page
    await page.close()


@pytest.fixture(scope="function")
def pact_mock():
    """Create a Pact mock server for testing"""
    pact = Consumer("ProfilePageUI").has_pact_with(
        Provider("ProfileAPI"),
        host_name="localhost",
        port=1234,  # Use a specific port for consistency
        pact_dir="./pacts",
    )

    pact.start_service()
    yield pact
    pact.stop_service()


@pytest.mark.asyncio
async def test_profile_form_submission(fastapi_server, page, pact_mock):
    """Test that the profile form submits data in the expected format"""

    # Set up the expected interaction in Pact
    pact_mock.given("ready for profile update").upon_receiving(
        "a profile update form submission"
    ).with_request(
        method="POST",
        path="/api/profile",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body={"name": "John Doe", "email": "john@example.com", "bio": "Test bio"},
    ).will_respond_with(
        status=200, headers={"Content-Type": "application/json"}, body={"success": True}
    )

    # Set up request interception to redirect to Pact mock server
    await page.route(
        "**/api/profile",
        lambda route: route.continue_(
            url=f"http://localhost:1234/api/profile",
            method=route.request.method,
            headers=route.request.headers,
            post_data=route.request.post_data,
        ),
    )

    # Navigate to the form page
    await page.goto(f"{fastapi_server}/profile")

    # Fill the form
    await page.fill("#name-input", "John Doe")
    await page.fill("#email-input", "john@example.com")
    await page.fill("#bio-input", "Test bio")

    # Submit the form
    await page.click("#submit-button")

    # Wait for response
    await page.wait_for_timeout(
        1000
    )  # Small delay to ensure Pact captures the interaction

    # Verify that Pact recorded the expected interaction
    pact_mock.verify()


@pytest.mark.asyncio
async def test_file_upload_form(fastapi_server, page, pact_mock):
    """Test that the file upload form submits data in the expected format"""

    # Set up the expected interaction in Pact
    pact_mock.given("ready for document upload").upon_receiving(
        "a document upload form submission"
    ).with_request(
        method="POST",
        path="/api/documents/upload",
        # Content-Type header will include boundary, so we use a regex matcher
        # Unfortunately, Pact-Python doesn't have a direct regex matcher for headers
        # We'll need to be less strict in our verification
    ).will_respond_with(
        status=200,
        headers={"Content-Type": "application/json"},
        body={"fileId": "doc-123"},
    )

    # Set up request interception to redirect to Pact mock server
    await page.route(
        "**/api/documents/upload",
        lambda route: route.continue_(
            url=f"http://localhost:1234/api/documents/upload",
            method=route.request.method,
            headers=route.request.headers,
            post_data=route.request.post_data,
        ),
    )

    # Navigate to the file upload page
    await page.goto(f"{fastapi_server}/document-upload")

    # Create a test file (using Playwright's file chooser)
    await page.set_input_files(
        "input[type=file]",
        # Create a temporary file
        {
            "name": "test.pdf",
            "mimeType": "application/pdf",
            "buffer": bytes("test pdf content", "utf-8"),
        },
    )

    # Fill other form fields
    await page.fill("#description-input", "Test document")

    # Submit the form
    await page.click("#upload-button")

    # Wait for response
    await page.wait_for_timeout(1000)

    # Verify that Pact recorded the expected interaction
    pact_mock.verify()


# ----- Helper Functions -----

from fastapi.responses import HTMLResponse


def create_test_html_files():
    """Create test HTML files for testing"""
    os.makedirs("static", exist_ok=True)

    # Create profile form HTML
    with open("static/profile.html", "w") as f:
        f.write(
            """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Profile Update</title>
        </head>
        <body>
            <h1>Update Your Profile</h1>
            <form action="/api/profile" method="post">
                <div>
                    <label for="name-input">Name:</label>
                    <input type="text" id="name-input" name="name" required>
                </div>
                <div>
                    <label for="email-input">Email:</label>
                    <input type="email" id="email-input" name="email" required>
                </div>
                <div>
                    <label for="bio-input">Bio:</label>
                    <textarea id="bio-input" name="bio"></textarea>
                </div>
                <button type="submit" id="submit-button">Update Profile</button>
            </form>
        </body>
        </html>
        """
        )

    # Create file upload form HTML
    with open("static/document-upload.html", "w") as f:
        f.write(
            """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Document Upload</title>
        </head>
        <body>
            <h1>Upload Document</h1>
            <form action="/api/documents/upload" method="post" enctype="multipart/form-data">
                <div>
                    <label for="document-input">Document:</label>
                    <input type="file" id="document-input" name="document" required>
                </div>
                <div>
                    <label for="description-input">Description:</label>
                    <input type="text" id="description-input" name="description" required>
                </div>
                <button type="submit" id="upload-button">Upload</button>
            </form>
        </body>
        </html>
        """
        )


if __name__ == "__main__":
    # Create test HTML files if running directly
    create_test_html_files()
    print("Test HTML files created. Run tests with: pytest -v test_profile_form.py")
