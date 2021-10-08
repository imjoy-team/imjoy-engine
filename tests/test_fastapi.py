from fastapi import FastAPI
import uvicorn

app = FastAPI()


@app.get("/add-route")
async def root():

    test_app = FastAPI()

    @test_app.get("/sub-path")
    async def sub_path():
        return {"message": "Hello World from /sub-path"}

    app.mount("/test", test_app)

    return {"message": "sub-path added!"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9923)
