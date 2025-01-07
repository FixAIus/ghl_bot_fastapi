from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import traceback
from redis import Redis
import os
import json
from threading import Thread
from functions import (
    validate_request_data,
    fetch_ghl_access_token,
    log,
    GoHighLevelAPI
)

app = FastAPI()

redis_url = os.getenv("REDIS_URL")
redis_client = Redis.from_url(redis_url, decode_responses=True)
redis_client.config_set("notify-keyspace-events", "Ex")

@app.post("/triggerResponse")
async def trigger_response(request: Request):
    try:
        request_data = await request.json()
        validated_fields = validate_request_data(request_data)

        if not validated_fields:
            return JSONResponse(content={"error": "Invalid request data"}, status_code=400)

        # Add validated fields to Redis with TTL
        redis_key = f"contact:{validated_fields['ghl_contact_id']}"
        result = redis_client.hset(redis_key, mapping=validated_fields)
        redis_client.expire(redis_key, 30)

        if result:
            log("info", f"Redis Queue --- Time Delay Started --- {validated_fields['ghl_contact_id']}",
                scope="Redis Queue", num_fields_added=result,
                fields_added=json.dumps(validated_fields),
                ghl_contact_id=validated_fields['ghl_contact_id'])
        else:
            log("info", f"Redis Queue --- Time Delay Reset --- {validated_fields['ghl_contact_id']}",
                scope="Redis Queue", num_fields_added=result,
                fields_added=json.dumps(validated_fields),
                ghl_contact_id=validated_fields['ghl_contact_id'])

        return JSONResponse(content={"message": "Response queued", "ghl_contact_id": validated_fields['ghl_contact_id']}, status_code=200)
    except Exception as e:
        log("error", f"Unexpected error: {str(e)}", traceback=traceback.format_exc())
        return JSONResponse(content={"error": "Internal server error"}, status_code=500)







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
