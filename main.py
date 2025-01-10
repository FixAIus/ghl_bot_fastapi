from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from openai import AsyncOpenAI
import os
import json
import traceback
import asyncio
from typing import Dict
from functions import (
    validate_request_data,
    fetch_ghl_access_token,
    make_redis_json_str,
    log,
    GoHighLevelAPI
)

app = FastAPI()

redis_url = os.getenv("REDIS_URL")
redis_client = Redis.from_url(redis_url, decode_responses=True)
conversation_queues: Dict[str, asyncio.Queue] = {}
processing_locks: Dict[str, asyncio.Lock] = {}

@app.on_event("startup")
async def startup_event():
    await redis_client.config_set("notify-keyspace-events", "Ex")

@app.on_event("shutdown")
async def shutdown_event():
    await redis_client.close()

openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
ghl_api = GoHighLevelAPI()

async def get_conversation_queue(contact_id: str) -> asyncio.Queue:
    if contact_id not in conversation_queues:
        conversation_queues[contact_id] = asyncio.Queue()
    return conversation_queues[contact_id]

async def get_processing_lock(contact_id: str) -> asyncio.Lock:
    if contact_id not in processing_locks:
        processing_locks[contact_id] = asyncio.Lock()
    return processing_locks[contact_id]

@app.post("/triggerResponse")
async def trigger_response(request: Request):
    try:
        request_data = await request.json()
        validated_fields = await validate_request_data(request_data)

        if not validated_fields:
            return JSONResponse(content={"error": "Invalid request data"}, status_code=400)

        redis_key = make_redis_json_str(validated_fields)
        result = await redis_client.setex(redis_key, 30, "0")

        contact_id = validated_fields["ghl_contact_id"]
        queue = await get_conversation_queue(contact_id)
        await queue.put(validated_fields)

        asyncio.create_task(process_conversation_queue(contact_id))

        if result:
            await log("info", f"Redis Queue --- Set time delay --- {contact_id}",
                      scope="Redis Queue", redis_key=redis_key, input_fields=validated_fields,
                      ghl_contact_id=contact_id)
            return JSONResponse(content={"message": "Response queued", "ghl_contact_id": contact_id}, status_code=200)
        else:
            await log("error", f"Redis Queue --- Failed to queue --- {contact_id}",
                      scope="Redis Queue", redis_key=redis_key, input_fields=validated_fields,
                      ghl_contact_id=contact_id)
            return JSONResponse(content={"message": "Failed to queue", "ghl_contact_id": contact_id}, status_code=500)

    except Exception as e:
        await log("error", f"Unexpected error during triggerResponse: {str(e)}", scope="Redis Queue", traceback=traceback.format_exc())
        return JSONResponse(content={"error": "Internal code error"}, status_code=500)

async def process_conversation_queue(contact_id: str):
    queue = await get_conversation_queue(contact_id)
    lock = await get_processing_lock(contact_id)

    async with lock:
        try:
            while not queue.empty():
                request_data = await queue.get()
                response = await process_assistant_conversation(request_data)

                if response and not response.get("error"):
                    await update_ghl_conversation(request_data, response)

                queue.task_done()
        except Exception as e:
            await log("error", f"Queue processing error for contact {contact_id}: {str(e)}", traceback=traceback.format_exc())

async def process_assistant_conversation(request_data: Dict) -> Dict:
    try:
        thread_id = request_data.get("thread_id")
        assistant_id = request_data.get("assistant_id")

        if not thread_id or not assistant_id:
            raise ValueError("Missing thread_id or assistant_id")

        # Placeholder for OpenAI Assistant processing
        return {
            "message": "Processed by assistant",
            "thread_id": thread_id
        }
    except Exception as e:
        await log("error", "Assistant processing error", error=str(e), traceback=traceback.format_exc())
        return {"error": str(e)}

async def update_ghl_conversation(request_data: Dict, response: Dict):
    try:
        if response.get("message"):
            contact_id = request_data.get("ghl_contact_id")
            convo_id = request_data.get("ghl_convo_id")

            if not contact_id or not convo_id:
                raise ValueError("Missing contact_id or convo_id")

            # Add logic to update GHL
            pass
    except Exception as e:
        await log("error", "GHL update error", error=str(e), traceback=traceback.format_exc())

@app.post("/moveConvoForward")
async def move_convo_forward(request: Request):
    try:
        request_data = await request.json()
        contact_id = request_data.get("ghl_contact_id")

        if not contact_id:
            return JSONResponse(content={"error": "Missing contact ID"}, status_code=400)

        queue = await get_conversation_queue(contact_id)
        await queue.put(request_data)
        asyncio.create_task(process_conversation_queue(contact_id))

        return JSONResponse(content={"message": "Request queued for processing", "ghl_contact_id": contact_id}, status_code=200)
    except Exception as e:
        await log("error", "GENERAL -- Unhandled exception in queue processing", scope="General", error=str(e), traceback=traceback.format_exc())
        return JSONResponse(content={"error": str(e), "traceback": traceback.format_exc()}, status_code=500)

@app.post("/testEndpoint")
async def test_endpoint(request: Request):
    try:
        data = await request.json()
        await log("info", "Received request parameters", **{
            k: data.get(k) for k in [
                "thread_id", "assistant_id", "ghl_contact_id", 
                "ghl_recent_message", "ghl_convo_id"
            ]
        })
        return JSONResponse(
            content={
                "response_type": "action, message, message_action",
                "action": {
                    "type": "force end, handoff, add_contact_id",
                    "details": {
                        "ghl_convo_id": data.get("ghl_convo_id", "")
                    }
                },
                "message": "Test response",
                "error": None
            },
            status_code=200
        )
    except Exception as e:
        await log("error", f"Unexpected error: {str(e)}", traceback=traceback.format_exc())
        return JSONResponse(content={"error": "Internal server error"}, status_code=500)
