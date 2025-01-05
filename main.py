"""
Asynchronous FastAPI server for AI conversation processing
Using asyncio and aiohttp for improved performance
"""

import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import traceback
import asyncio
from typing import Dict, Optional
from functions import (
    log,
    GHLResponseObject,
    validate_request_data,
    get_conversation_id,
    retrieve_and_compile_messages,
    run_ai_thread,
    process_message_response,
    process_function_response
)

# Load environment variables
load_dotenv()

# Verify required environment variables
required_env_vars = [
    "OPENAI_API_KEY",
    "GHL_ACCESS",
    "RAILWAY_API_TOKEN",
    "GHL_REFRESH"
]

missing_vars = [var for var in required_env_vars if not os.getenv(var)]
if missing_vars:
    raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

# Optimize for concurrent connections
MAX_CONCURRENT_REQUESTS = 6
QUEUE_WORKERS = 4

# Request Models
class ConversationRequest(BaseModel):
    thread_id: str
    assistant_id: str
    ghl_contact_id: str
    ghl_recent_message: str
    ghl_convo_id: str
    add_convo_id_action: Optional[bool] = Field(default=False)

class TestRequest(BaseModel):
    thread_id: Optional[str] = None
    assistant_id: Optional[str] = None
    ghl_contact_id: Optional[str] = None
    ghl_recent_message: Optional[str] = None
    ghl_convo_id: Optional[str] = None

app = FastAPI(
    title="AI Conversation API",
    description="API for handling AI-powered conversations",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request queue settings
REQUEST_QUEUE: Dict[str, asyncio.Queue] = {}
processing_semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

async def get_or_create_queue(contact_id: str) -> asyncio.Queue:
    """
    Get or create an unlimited queue for a specific contact
    """
    if contact_id not in REQUEST_QUEUE:
        REQUEST_QUEUE[contact_id] = asyncio.Queue()
    return REQUEST_QUEUE[contact_id]

async def process_queued_request(contact_id: str, request_data: ConversationRequest):
    """
    Process a single request from the queue asynchronously
    """
    async with processing_semaphore:
        queue = await get_or_create_queue(contact_id)
        
        try:
            res_obj = GHLResponseObject()
            
            # Validate request data
            validated_fields = await validate_request_data(request_data.dict())
            if not validated_fields:
                raise HTTPException(status_code=400, detail="Invalid request data")

            # Extract conversation ID
            ghl_convo_id = validated_fields["ghl_convo_id"]
            if validated_fields.get("add_convo_id_action"):
                res_obj.add_action("add_convo_id", {"ghl_convo_id": ghl_convo_id})

            # Process messages
            new_messages = await retrieve_and_compile_messages(
                ghl_convo_id,
                validated_fields["ghl_recent_message"],
                validated_fields["ghl_contact_id"]
            )
            if not new_messages:
                raise HTTPException(status_code=400, detail="No messages added")

            # Run AI processing
            run_response, run_status, run_id = await run_ai_thread(
                validated_fields["thread_id"],
                validated_fields["assistant_id"],
                new_messages,
                validated_fields["ghl_contact_id"]
            )

            # Handle response types
            if run_status == "completed":
                ai_content = await process_message_response(
                    validated_fields["thread_id"],
                    run_id,
                    validated_fields["ghl_contact_id"]
                )
                if not ai_content:
                    raise HTTPException(status_code=404, detail="No AI messages found")
                res_obj.add_message(ai_content)

            elif run_status == "requires_action":
                generated_function = await process_function_response(
                    validated_fields["thread_id"],
                    run_id,
                    run_response,
                    validated_fields["ghl_contact_id"]
                )
                res_obj.add_action(generated_function)

            else:
                await log("error", f"AI Run Failed -- {validated_fields['ghl_contact_id']}", 
                    scope="AI Run", run_status=run_status, run_id=run_id, 
                    thread_id=validated_fields['thread_id'])
                raise HTTPException(status_code=400, detail=f"Run {run_status}")

            return res_obj.get_response()
            
        except HTTPException:
            raise
        except Exception as e:
            tb_str = traceback.format_exc()
            await log("error", "QUEUE -- Request processing failed",
                scope="Queue", error=str(e), traceback=tb_str,
                contact_id=contact_id)
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            # Remove completed request from queue
            await queue.get()
            queue.task_done()

@app.post("/moveConvoForward", 
    summary="Process a conversation message",
    response_description="Processed conversation response")
async def move_convo_forward(request: ConversationRequest):
    """
    Process an incoming conversation message with the AI assistant.
    
    - Queues the request for processing
    - Handles the conversation flow
    - Returns the AI response or action
    """
    try:
        contact_id = request.ghl_contact_id
        queue = await get_or_create_queue(contact_id)
        
        # Add request to queue
        await queue.put(request)
        await log("info", f"Request queued for contact {contact_id}", 
            queue_size=queue.qsize())
        
        # Process the request
        return await process_queued_request(contact_id, request)

    except HTTPException:
        raise
    except Exception as e:
        tb_str = traceback.format_exc()
        await log("error", "GENERAL -- Unhandled exception in queue processing",
            scope="General", error=str(e), traceback=tb_str)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/testEndpoint", 
    summary="Test endpoint for format verification",
    response_description="Example response format")
async def test_endpoint(request: TestRequest):
    """
    Test endpoint that demonstrates the expected response format
    """
    await log("info", "Received request parameters", **request.dict())
    return {
        "response_type": "action, message, message_action",
        "action": {
            "type": "force end, handoff, add_contact_id",
            "details": {
                "ghl_convo_id": "afdlja;ldf"
            }
        },
        "message": "wwwwww",
        "error": "booo error"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "5000")))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
