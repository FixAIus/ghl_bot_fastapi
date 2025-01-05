import json
import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import traceback
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
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from asyncio import Queue
from typing import Dict, Optional

# Optimize for 8 vCPUs
MAX_CONCURRENT_REQUESTS = 6
THREAD_POOL_SIZE = 8
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

# Initialize thread pool
thread_pool = ThreadPoolExecutor(max_workers=THREAD_POOL_SIZE)

# Request queue settings
REQUEST_QUEUE: Dict[str, Queue] = {}
processing_semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

async def get_or_create_queue(contact_id: str) -> Queue:
    """
    Get or create an unlimited queue for a specific contact
    """
    if contact_id not in REQUEST_QUEUE:
        REQUEST_QUEUE[contact_id] = Queue()
    return REQUEST_QUEUE[contact_id]

async def parallel_executor(func, *args, **kwargs):
    """
    Execute CPU-bound tasks in the thread pool
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(thread_pool, partial(func, *args, **kwargs))

async def process_queued_request(contact_id: str, request_data: ConversationRequest):
    """
    Process a single request from the queue with optimized resource usage
    """
    async with processing_semaphore:
        queue = await get_or_create_queue(contact_id)
        
        try:
            res_obj = GHLResponseObject()
            
            # Validate request data using parallel executor
            validated_fields = await parallel_executor(
                validate_request_data, 
                request_data.dict()
            )
            if not validated_fields:
                raise HTTPException(status_code=400, detail="Invalid request data")

            # Extract conversation ID
            ghl_convo_id = validated_fields["ghl_convo_id"]
            if validated_fields.get("add_convo_id_action"):
                res_obj.add_action("add_convo_id", {"ghl_convo_id": ghl_convo_id})

            # Process messages in parallel
            new_messages = await parallel_executor(
                retrieve_and_compile_messages,
                ghl_convo_id,
                validated_fields["ghl_recent_message"],
                validated_fields["ghl_contact_id"]
            )
            if not new_messages:
                raise HTTPException(status_code=400, detail="No messages added")

            # Run AI processing in parallel
            run_response, run_status, run_id = await parallel_executor(
                run_ai_thread,
                validated_fields["thread_id"],
                validated_fields["assistant_id"],
                new_messages,
                validated_fields["ghl_contact_id"]
            )

            # Handle response types
            if run_status == "completed":
                ai_content = await parallel_executor(
                    process_message_response,
                    validated_fields["thread_id"],
                    run_id,
                    validated_fields["ghl_contact_id"]
                )
                if not ai_content:
                    raise HTTPException(status_code=404, detail="No AI messages found")
                res_obj.add_message(ai_content)

            elif run_status == "requires_action":
                generated_function = await parallel_executor(
                    process_function_response,
                    validated_fields["thread_id"],
                    run_id,
                    run_response,
                    validated_fields["ghl_contact_id"]
                )
                res_obj.add_action(generated_function)

            else:
                log("error", f"AI Run Failed -- {validated_fields['ghl_contact_id']}", 
                    scope="AI Run", run_status=run_status, run_id=run_id, 
                    thread_id=validated_fields['thread_id'])
                raise HTTPException(status_code=400, detail=f"Run {run_status}")

            return res_obj.get_response()
            
        except HTTPException:
            raise
        except Exception as e:
            tb_str = traceback.format_exc()
            log("error", "QUEUE -- Request processing failed",
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
        log("info", f"Request queued for contact {contact_id}", 
            queue_size=queue.qsize())
        
        # Process the request
        return await process_queued_request(contact_id, request)

    except HTTPException:
        raise
    except Exception as e:
        tb_str = traceback.format_exc()
        log("error", "GENERAL -- Unhandled exception in queue processing",
            scope="General", error=str(e), traceback=tb_str)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/testEndpoint", 
    summary="Test endpoint for format verification",
    response_description="Example response format")
async def test_endpoint(request: TestRequest):
    """
    Test endpoint that demonstrates the expected response format
    """
    log("info", "Received request parameters", **request.dict())
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

@app.on_event("startup")
async def startup_event():
    """
    Initialize resources before the server starts
    """
    global thread_pool
    thread_pool = ThreadPoolExecutor(max_workers=THREAD_POOL_SIZE)

@app.on_event("shutdown")
async def shutdown_event():
    """
    Clean up resources when the server shuts down
    """
    thread_pool.shutdown(wait=True)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
