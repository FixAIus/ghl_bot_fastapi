import os
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import traceback
from typing import Dict, Optional, Any
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
from asyncio import Queue

# Configuration constants
MAX_CONCURRENT_REQUESTS = 6
QUEUE_WORKERS = 4

app = FastAPI()

# Request queue and processing settings
REQUEST_QUEUE: Dict[str, Queue] = {}
processing_semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

class ConversationRequest(BaseModel):
    thread_id: str
    assistant_id: str
    ghl_contact_id: str
    ghl_recent_message: str
    ghl_convo_id: Optional[str] = None

class ConversationResponse(BaseModel):
    response_type: Optional[str] = None
    action: Optional[Dict[str, Any]] = None
    message: Optional[str] = None
    error: Optional[str] = None

async def get_or_create_queue(contact_id: str) -> Queue:
    """Get or create an unlimited queue for a specific contact"""
    if contact_id not in REQUEST_QUEUE:
        REQUEST_QUEUE[contact_id] = Queue()
    return REQUEST_QUEUE[contact_id]

async def process_queued_request(contact_id: str, request_data: dict):
    """Process a single request from the queue"""
    async with processing_semaphore:
        queue = await get_or_create_queue(contact_id)
        
        try:
            res_obj = GHLResponseObject()
            
            # Validate request data
            validated_fields = await validate_request_data(request_data)
            if not validated_fields:
                raise HTTPException(status_code=400, detail="Invalid request data")

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
            raise HTTPException(status_code=500, detail={
                "error": str(e),
                "traceback": tb_str
            })
        finally:
            # Remove completed request from queue
            await queue.get()
            queue.task_done()

@app.post('/moveConvoForward', response_model=ConversationResponse)
async def move_convo_forward(
    request: ConversationRequest,
    background_tasks: BackgroundTasks
):
    """
    Asynchronous endpoint with request queueing for handling conversation flow.
    All requests are accepted and processed in order per contact.
    """
    try:
        if not request.ghl_contact_id:
            raise HTTPException(status_code=400, detail="Missing contact ID")
            
        # Get or create queue for this contact
        queue = await get_or_create_queue(request.ghl_contact_id)
        
        # Add request to queue
        await queue.put(request.dict())
        log("info", f"Request queued for contact {request.ghl_contact_id}", 
            queue_size=queue.qsize())
        
        # Process the request
        response = await process_queued_request(request.ghl_contact_id, request.dict())
        return response

    except HTTPException:
        raise
    except Exception as e:
        tb_str = traceback.format_exc()
        log("error", "GENERAL -- Unhandled exception in queue processing",
            scope="General", error=str(e), traceback=tb_str)
        raise HTTPException(status_code=500, detail={
            "error": str(e),
            "traceback": tb_str
        })

@app.post('/testEndpoint', response_model=ConversationResponse)
async def test_format(request: ConversationRequest):
    """Test endpoint that demonstrates the expected response format"""
    log("info", "Received request parameters", **request.dict())
    return ConversationResponse(
        response_type="action, message, message_action",
        action={
            "type": "force end, handoff, add_contact_id",
            "details": {
                "ghl_convo_id": "afdlja;ldf"
            }
        },
        message="wwwwww",
        error="booo error"
    )

if __name__ == '__main__':
    import hypercorn.asyncio
    
    config = hypercorn.Config()
    config.bind = [f"0.0.0.0:{os.getenv('PORT', '5000')}"]
    config.worker_class = "asyncio"
    
    asyncio.run(hypercorn.asyncio.serve(app, config))

