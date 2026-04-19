from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def hello_world():
    return {"message": "Hello, World!"}


@app.get("/status")
def status():
    return {"status": "ok", "version": "1.0.0"}
