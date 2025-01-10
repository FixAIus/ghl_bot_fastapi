from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from openai import AsyncOpenAI
import os
import json
import traceback
import httpx
import asyncio
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
@app.on_event("startup")
async def startup_event():
    await redis_client.config_set("notify-keyspace-events", "Ex")
@app.on_event("shutdown")
async def shutdown_event():
    await redis_client.close()


openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

ghl_api = GoHighLevelAPI()


@app.post("/triggerResponse")
async def trigger_response(request: Request):
    try:
        request_data = await request.json()
        validated_fields = await validate_request_data(request_data)

        if not validated_fields:
            return JSONResponse(content={"error": "Invalid request data"}, status_code=400)

        # Add validated fields to Redis with TTL
        redis_key = make_redis_json_str(validated_fields)
        result = await redis_client.setex(redis_key, 30, "0")

        if result:
            await log("info", f"Redis Queue --- Set time delay --- {validated_fields['ghl_contact_id']}",
                      scope="Redis Queue", redis_key=redis_key, input_fields=validated_fields,
                      ghl_contact_id=validated_fields['ghl_contact_id'])
            return JSONResponse(content={"message": "Response queued", "ghl_contact_id": validated_fields['ghl_contact_id']}, status_code=200)

        else:
            await log("error", f"Redis Queue --- Failed to queue --- {validated_fields['ghl_contact_id']}",
                      scope="Redis Queue", redis_key=redis_key, input_fields=validated_fields,
                      ghl_contact_id=validated_fields['ghl_contact_id'])
            return JSONResponse(content={"message": "Failed to queue", "ghl_contact_id": validated_fields['ghl_contact_id']}, status_code=200)

    except Exception as e:
        await log("error", f"Unexpected error during triggerResponse: {str(e)}", scope="Redis Queue", traceback=traceback.format_exc())
        return JSONResponse(content={"error": "Internal code error"}, status_code=500)





@app.post("/initialize")
async def initialize(request: Request):
    try:
        data = await request.json()
        await log("info", "Initialization -- Start", scope="Initialize", input=data)
        ghl_contact_id = data.get("ghl_contact_id")
        first_message = data.get("first_message")
        bot_filter_tag = data.get("bot_filter_tag")

        if not (ghl_contact_id and first_message and bot_filter_tag):
            await log("error", "Missing required fields -- Canceling bot", 
                      scope="Initialize", data=data, ghl_contact_id=data.get("ghl_contact_id"))
            return JSONResponse(content={"error": "Missing required fields"}, status_code=400)

        # Step 1: Create a new thread in OpenAI
        thread_response = await openai_client.beta.threads.create(
            messages=[{"role": "assistant", "content": first_message}]
        )
        thread_id = thread_response.id
        if not thread_id or thread_id in ["", "null", None]:
            await log("error", "Failed to start thread -- Canceling bot", scope="Initialize", thread_response=thread_response, data=data)
            return JSONResponse(content={"error": "Failed to start thread"}, status_code=400)

        # Step 2: Get convo_id and send updates to GHL contact
        convo_id = await ghl_api.get_conversation_id(ghl_contact_id)
        if not convo_id:
            return JSONResponse(content={"error": "Failed to get convo id"}, status_code=400)

        message_response = await ghl_api.send_message(first_message, ghl_contact_id)
        if not message_response:
            return JSONResponse(content={"error": "Failed to send message"}, status_code=400)
        message_id = message_response["messageId"]

        update_data = {
            "customFields": [
                {"key": "ghl_convo_id", "field_value": convo_id},
                {"key": "thread_id", "field_value": thread_id},
                {"key": "recent_automated_message_id", "field_value": message_id}
            ]
        }
        update_response = await ghl_api.update_contact(ghl_contact_id, update_data)
        if not update_response:
            return JSONResponse(content={"error": "Failed update contact"}, status_code=400)

        # Step 3: Add bot filter tag
        tag_response = await ghl_api.add_tag(ghl_contact_id, [bot_filter_tag])
        if not tag_response:
            return JSONResponse(content={"error": "Failed update contact"}, status_code=400)

        await log("info", f"Initialization -- Success -- {ghl_contact_id}",
                  scope="Initialize", ghl_contact_id=ghl_contact_id, input=data, output=update_data)

        return JSONResponse(content={"message": "Initialization successful", "ghl_contact_id": ghl_contact_id}, status_code=200)
    except Exception as e:
        await log("error", f"Unexpected error during initialization: {str(e)}", scope="Initialize", traceback=traceback.format_exc())
        return JSONResponse(content={"error": "Internal code error"}, status_code=500)





@app.post("/testEndpoint")
async def test_endpoint(request: Request):
    try:
        data = await request.json()
        log("info", "Received request parameters", **{
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
                        "ghl_convo_id": "afdlja;ldf"
                    }
                },
                "message": "wwwwww",
                "error": "booo error"
            },
            status_code=200
        )
    except Exception as e:
        log("error", f"Unexpected error: {str(e)}", traceback=traceback.format_exc())
        return JSONResponse(content={"error": "Internal server error"}, status_code=500)
