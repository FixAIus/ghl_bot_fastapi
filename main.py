from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from functions import log  # Import the log function from functions.py

# Define a Pydantic model for request validation
class RequestData(BaseModel):
    ghl_contact_id: str
    thread_id: str
    opportunity_stage: str

app = FastAPI()

@app.post("/update-opportunity")
async def update_opportunity(data: RequestData):
    await log("info", "Request  received")
    try:
        # Placeholder logic for valid requests
        # TODO: Implement the actual logic for updating the opportunity
        log("info", "Valid request received")
    except Exception as e:
        # Log the error if required fields are missing
        await log("error", "Invalid Request", data=data.dict())
        raise HTTPException(status_code=400, detail="Invalid Request")
