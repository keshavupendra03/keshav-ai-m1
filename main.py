from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager
from pool import KeshavAIPool
import os
import uvicorn

# Number of parallel browser workers. Each worker is a full Chromium
# instance loading the heavy chatgpt.com app, so this is almost
# entirely a RAM question, not a CPU one. Render's smallest instance
# gives 512Mi total - a single loaded Chromium tab alone can use a
# few hundred MB, so POOL_SIZE=3 reliably OOM-kills the container
# before it ever finishes starting (confirmed in deploy logs).
#
# Read from the environment so this can be tuned per-deployment
# without a code change: set POOL_SIZE/HEADLESS in Render's
# environment variables. Defaults here are deliberately conservative
# (safe for a memory-constrained host); bump POOL_SIZE up locally via
# `set POOL_SIZE=3` (PowerShell: `$env:POOL_SIZE=3`) if you want
# concurrent workers on a machine with enough RAM to spare.
POOL_SIZE = int(os.environ.get("POOL_SIZE", "1"))
HEADLESS = os.environ.get("HEADLESS", "true").lower() != "false"

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
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
