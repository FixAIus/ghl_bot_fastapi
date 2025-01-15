from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
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
    GoHighLevelAPI,
    KILL_BOT
)
import uuid

IS_LOAD_TEST = os.getenv("LOAD_TEST_MODE", "false").lower() == "true"
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
TEST_REDIS_PREFIX = "loadtest:"

app = FastAPI()

@app.get("/loaderio-9f905956f9bac67c3b7f9ad9c24c0c9f.txt")
async def serve_loaderio_verification():
    return PlainTextResponse("loaderio-9f905956f9bac67c3b7f9ad9c24c0c9f")

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





@app.post("/initialize")
async def initialize(request: Request):
    try:
        incoming = await request.json()
        data = incoming.get("customData")

        ghl_contact_id = data.get("ghl_contact_id")
        first_message = data.get("first_message")
        bot_filter_tag = data.get("bot_filter_tag")

        if not (ghl_contact_id and first_message and bot_filter_tag):
            await log("error", "Missing required fields", 
                      scope="Initialize", data=data, ghl_contact_id=data.get("ghl_contact_id"))
            return JSONResponse(content={"error": "Missing required fields"}, status_code=400)

        try:
            # Step 1: Create a new thread in OpenAI
            thread_response = await openai_client.beta.threads.create(
                messages=[{"role": "assistant", "content": first_message}]
            )
            thread_id = thread_response.id
            if not thread_id or thread_id in ["", "null", None]:
                raise Exception("Failed to start thread")

            # Step 2: Get convo_id and send updates to GHL contact
            convo_id = await ghl_api.get_conversation_id(ghl_contact_id)
            if not convo_id:
                raise Exception("Failed to get convo id")

            message_response = await ghl_api.send_message(ghl_contact_id, first_message)
            if not message_response:
                raise Exception("Failed to send message")
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
                raise Exception("Failed to update contact")

            # Step 3: Add bot filter tag
            tag_response = await ghl_api.add_tags(ghl_contact_id, [bot_filter_tag])
            if not tag_response:
                raise Exception("Failed to add bot filter tag")

            await log("info", f"Initialization -- Success -- {ghl_contact_id}",
                      scope="Initialize", ghl_contact_id=ghl_contact_id, input=data, output=update_data)

            return JSONResponse(content={"message": "Initialization successful", "ghl_contact_id": ghl_contact_id}, status_code=200)

        except Exception as e:
            await KILL_BOT(
                "Bot Failure", 
                ghl_contact_id, 
                [
                    (ghl_api.remove_tags, (ghl_contact_id, ["bott"]), {}, 1),
                    (ghl_api.add_tags, (ghl_contact_id, ["bot failure"]), {}, 1)
                ]
            )
            return JSONResponse(content={"error": str(e)}, status_code=400)

    except Exception as e:
        await log("error", f"Unexpected error during initialization: {str(e)}", scope="Initialize", traceback=traceback.format_exc())
        return JSONResponse(content={"error": "Internal code error"}, status_code=500)




###### TESTING PURPOSES ###
@app.post("/triggerResponse")
async def trigger_response(request: Request):
    try:
        # Safety check for production
        if IS_LOAD_TEST and ENVIRONMENT == "production":
            return JSONResponse(
                content={"error": "Load testing not allowed in production"}, 
                status_code=403
            )

        request_data = await request.json()
        
        # Bypass validation for load testing
        if IS_LOAD_TEST:
            validated_fields = {
                "ghl_contact_id": "test_contact",
                "thread_id": "test_thread",
                "assistant_id": "test_assistant",
                "recent_automated_message_id": "test_message",
                "ghl_convo_id": "test_convo"
            }
            redis_key = f"{TEST_REDIS_PREFIX}{uuid.uuid4()}"
        else:
            validated_fields = await validate_request_data(request_data)
            redis_key = make_redis_json_str(validated_fields)

        # Set in Redis with TTL
        result = await redis_client.setex(redis_key, 10, "0")

        if result:
            return JSONResponse(
                content={"message": "Response queued", "ghl_contact_id": validated_fields['ghl_contact_id']}, 
                status_code=200
            )
        else:
            return JSONResponse(
                content={"message": "Failed to queue", "ghl_contact_id": validated_fields['ghl_contact_id']}, 
                status_code=200
            )

    except Exception as e:
        await log("error", f"Trigger Response: Unexpected error: {str(e)}", scope="Trigger Response")
        return JSONResponse(content={"error": "Internal code error"}, status_code=500)
### ENDING TESTING CODE ###

 ### ORIGINAL CODE ###
# @app.post("/triggerResponse")
# async def trigger_response(request: Request):
#     try:
#         request_data = await request.json()
#         validated_fields = await validate_request_data(request_data)

#         if not validated_fields:
#             ghl_contact_id=request_data.get("ghl_contact_id")
#             bot_filter_tag=request_data.get("bot_filter_tag")
#             await KILL_BOT(
#                 "Bot Failure", 
#                 ghl_contact_id, 
#                 [
#                     (ghl_api.remove_tags, (ghl_contact_id, [bot_filter_tag]), {}, 1),
#                     (ghl_api.add_tags, (ghl_contact_id, ["bot failure"]), {}, 1)
#                 ]
#             )
#             return JSONResponse(content={"error": "Invalid request data"}, status_code=400)

#         # Add validated fields to Redis with TTL
#         redis_key = make_redis_json_str(validated_fields)
#         result = await redis_client.setex(redis_key, 10, "0")

#         if result:
#             await log("info", f"Trigger Response --- Time delay set --- {validated_fields['ghl_contact_id']}",
#                       scope="Trigger Response", redis_key=redis_key, input_fields=validated_fields,
#                       ghl_contact_id=validated_fields['ghl_contact_id'])
#             return JSONResponse(content={"message": "Response queued", "ghl_contact_id": validated_fields['ghl_contact_id']}, status_code=200)

#         else:
#             await log("error", f"Trigger Response --- Failed to queue --- {validated_fields['ghl_contact_id']}",
#                       scope="Trigger Response", redis_key=redis_key, input_fields=validated_fields,
#                       ghl_contact_id=validated_fields['ghl_contact_id'])
#             return JSONResponse(content={"message": "Failed to queue", "ghl_contact_id": validated_fields['ghl_contact_id']}, status_code=200)

#     except Exception as e:
#         await log("error", f"Trigger Response: Unexpected error: {str(e)}", scope="Trigger Response", traceback=traceback.format_exc())
#         return JSONResponse(content={"error": "Internal code error"}, status_code=500)
### END ORIGINAL CODE ###










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

@app.post("/cleanup-loadtest")
async def cleanup_loadtest():
    if not IS_LOAD_TEST:
        return JSONResponse(content={"error": "Not in load test mode"}, status_code=403)
    
    try:
        test_keys = await redis_client.keys(f"{TEST_REDIS_PREFIX}*")
        if test_keys:
            await redis_client.delete(*test_keys)
        return JSONResponse(content={"message": f"Cleaned up {len(test_keys)} test keys"}, status_code=200)
    except Exception as e:
        return JSONResponse(content={"error": f"Cleanup failed: {str(e)}"}, status_code=500)

@app.get("/loadtest")
async def load_test():
    try:
        return JSONResponse(
            content={"status": "success"}, 
            status_code=200
        )
    except Exception as e:
        return JSONResponse(
            content={"error": str(e)}, 
            status_code=500
        )

@app.post("/loadtest/full-flow")
async def full_flow_test():
    try:
        # 1. Simulate OpenAI thread creation
        thread_id = f"thread_{uuid.uuid4()}"
        await asyncio.sleep(0.1)  # Simulate API delay
        
        # 2. Simulate Redis operations
        redis_key = f"loadtest:{thread_id}"
        await redis_client.setex(redis_key, 10, "test_value")
        
        # 3. Simulate GHL operations
        mock_ghl_response = {
            "contact_id": f"contact_{uuid.uuid4()}",
            "conversation_id": f"convo_{uuid.uuid4()}",
            "message_id": f"msg_{uuid.uuid4()}"
        }
        await asyncio.sleep(0.2)  # Simulate API delay
        
        # 4. Simulate full process completion
        return JSONResponse(
            content={
                "status": "success",
                "flow": "complete",
                "thread_id": thread_id,
                "ghl_data": mock_ghl_response,
                "redis_key": redis_key
            }, 
            status_code=200
        )
        
    except Exception as e:
        await log("error", f"Full flow test failed: {str(e)}")
        return JSONResponse(
            content={"error": str(e)}, 
            status_code=500
        )

# Optional: Add endpoint to test with configurable delays
@app.post("/loadtest/full-flow/{delay}")
async def full_flow_test_with_delay(delay: float):
    try:
        # Cap maximum delay for safety
        delay = min(float(delay), 2.0)
        
        # 1. OpenAI simulation
        await asyncio.sleep(delay * 0.3)  # 30% of delay
        thread_id = f"thread_{uuid.uuid4()}"
        
        # 2. Redis operation
        redis_key = f"loadtest:{thread_id}"
        await redis_client.setex(redis_key, 10, "test_value")
        
        # 3. GHL simulation
        await asyncio.sleep(delay * 0.7)  # 70% of delay
        mock_ghl_response = {
            "contact_id": f"contact_{uuid.uuid4()}",
            "conversation_id": f"convo_{uuid.uuid4()}",
            "message_id": f"msg_{uuid.uuid4()}"
        }
        
        return JSONResponse(
            content={
                "status": "success",
                "flow": "complete",
                "thread_id": thread_id,
                "ghl_data": mock_ghl_response,
                "redis_key": redis_key,
                "total_delay": delay
            }, 
            status_code=200
        )
        
    except Exception as e:
        await log("error", f"Full flow test with delay failed: {str(e)}")
        return JSONResponse(
            content={"error": str(e)}, 
            status_code=500
        )

@app.get("/loadtest/full-cycle")
async def full_cycle_test():
    try:
        # Step 1: Simulate OpenAI thread creation
        thread_id = f"thread_{uuid.uuid4()}"
        await asyncio.sleep(0.1)  # Simulate API delay
        
        # Step 2: Simulate Redis operations
        redis_key = f"loadtest:{thread_id}"
        await redis_client.setex(redis_key, 20, json.dumps({
            "thread_id": thread_id,
            "status": "processing"
        }))
        
        # Step 3: Simulate GHL operations
        mock_message = {
            "messageId": f"msg_{uuid.uuid4()}",
            "content": "Test message"
        }
        await asyncio.sleep(0.2)  # Simulate API delay
        
        # Step 4: Update Redis with result
        await redis_client.setex(redis_key, 10, json.dumps({
            "thread_id": thread_id,
            "status": "complete",
            "message": mock_message
        }))
        
        return JSONResponse(
            content={
                "status": "success",
                "steps_completed": {
                    "openai": True,
                    "redis": True,
                    "ghl": True
                },
                "thread_id": thread_id,
                "message_id": mock_message["messageId"]
            }, 
            status_code=200
        )
        
    except Exception as e:
        await log("error", f"Full cycle test failed: {str(e)}")
        return JSONResponse(
            content={"error": str(e)}, 
            status_code=500
        )
