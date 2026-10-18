from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager
from pool import KeshavAIPool
import uvicorn

# Number of parallel browser workers. Each worker is a full headless
# Chromium page, so this trades RAM/CPU for lower wait time under
# concurrent load. Tune based on expected simultaneous users and
# available server resources.
#
# HEADLESS = False opens a real, visible Chromium window per worker
# so you can watch the automation happen live. Keep POOL_SIZE at 1
# while doing this - otherwise N windows pop up at once and it's
# hard to follow any single one. Set both back (4 / True) for normal
# headless/concurrent use once you're done observing.
POOL_SIZE = 3
HEADLESS = True

pool = KeshavAIPool(size=POOL_SIZE, headless=HEADLESS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting Keshav AI...")
    await pool.start()
    print("Keshav AI is ready!")
    yield
    await pool.close()
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
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    try:
        answer = await pool.ask(request.question)
        return {"answer": answer}

    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))

    except RuntimeError as e:
        # All retry attempts were exhausted (see KeshavAIPool.ask) -
        # a clear "try again" signal, not a silent fake answer.
        raise HTTPException(status_code=503, detail=str(e))

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
