from fastapi import FastAPI

app = FastAPI(title="Chat App")


@app.get("/")
def read_root():
    return {"message": "Welcome to the Chat App API"} 