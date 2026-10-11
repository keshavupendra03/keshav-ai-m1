from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager
from keshav_AI import KeshavAIBot
import uvicorn

bot = KeshavAIBot(headless=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting Keshav AI...")
    await bot.start()
    print("Keshav AI is ready!")
    yield
    await bot.close()
    print("Keshav AI stopped.")


app = FastAPI(
    title="Keshav AI",
    description="Keshav AI API",
    version="1.0",
    lifespan=lifespan
)


class QuestionRequest(BaseModel):
    question: str


class AnswerResponse(BaseModel):
    answer: str


@app.post("/ask", response_model=AnswerResponse)
async def ask_question(request: QuestionRequest):
    try:
        if not request.question.strip():
            raise HTTPException(status_code=400, detail="Question cannot be empty")

        answer = await bot.ask(request.question)
        return {"answer": answer}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def home():
    return {
        "message": "Welcome to Keshav AI API",
        "endpoint": "POST /ask",
        "example": {
            "question": "What is an LLM?"
        }
    }



@app.get("/health")
async def health():
    return {"status": "ok"}



if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
