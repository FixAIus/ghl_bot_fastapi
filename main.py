from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from redis.asyncio import Redis
from openai import AsyncOpenAI
import os
import random
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
    KILL_BOT,
    authenticate
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





@app.post("/initialize")
async def initialize(request: Request):
    try:
        incoming = await request.json()
        data = incoming.get("customData")
        
        # Get API key from headers
        api_key = request.headers.get("x-api-key")
        if not api_key:
            await log("error", "Missing API key", scope="Initialize")
            return JSONResponse(content={"error": "Missing API key"}, status_code=401)
            
        # Verify API key
        if not await authenticate(api_key):
            await log("error", "Invalid API key", scope="Initialize")
            return JSONResponse(content={"error": "Invalid API key"}, status_code=401)

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

            # New Step: Create Airtable opportunity record
            async with httpx.AsyncClient() as client:
                airtable_response = await client.post(
                    "http://airtable.railway.internal:8080/create-opportunity",
                    json={
                        "customData": {
                            "ghl_contact_id": ghl_contact_id,
                            "thread_id": thread_id,
                            "opportunity_stage": "AI Bot"
                        }
                    }
                )
                airtable_data = airtable_response.json()
                
                if not airtable_response.status_code == 200 or not airtable_data.get("success"):
                    raise Exception("Failed to create Airtable record")
                    
                airtable_record_id = airtable_data["record_id"]
                
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
                    {"key": "recent_automated_message_id", "field_value": message_id},
                    {"key": "airtable_record_id", "field_value": airtable_record_id}
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
                    (ghl_api.remove_tags, (ghl_contact_id, ["bott"]), {}, 2),
                    (ghl_api.add_tags, (ghl_contact_id, ["bot failure"]), {}, 1)
                ]
            )
            return JSONResponse(content={"error": str(e)}, status_code=400)

    except Exception as e:
        await log("error", f"Unexpected error during initialization: {str(e)}", scope="Initialize", traceback=traceback.format_exc())
        return JSONResponse(content={"error": "Internal code error"}, status_code=500)





@app.post("/triggerResponse")
async def trigger_response(request: Request):
    try:
        incoming = await request.json()
        data = incoming.get("customData")
        
        # Get API key from headers
        api_key = request.headers.get("x-api-key")
        if not api_key:
            await log("error", "Missing API key", scope="Trigger Response")
            return JSONResponse(content={"error": "Missing API key"}, status_code=401)
            
        # Verify API key
        if not await authenticate(api_key):
            await log("error", "Invalid API key", scope="Trigger Response")
            return JSONResponse(content={"error": "Invalid API key"}, status_code=401)
        
        validated_fields = await validate_request_data(data)

        if not validated_fields:
            ghl_contact_id=data.get("ghl_contact_id")
            bot_filter_tag=data.get("bot_filter_tag")
            await KILL_BOT(
                "Bot Failure", 
                ghl_contact_id, 
                [
                    (ghl_api.remove_tags, (ghl_contact_id, [bot_filter_tag]), {}, 2),
                    (ghl_api.add_tags, (ghl_contact_id, ["bot failure"]), {}, 1)
                ]
            )
            return JSONResponse(content={"error": "Invalid request data"}, status_code=400)

        # Add validated fields to Redis with TTL
        redis_key = make_redis_json_str(validated_fields)
        result = await redis_client.setex(redis_key, random.randint(60, 180), "0")

        if result:
            await log("info", f"Trigger Response --- Time delay set --- {validated_fields['ghl_contact_id']}",
                      scope="Trigger Response", redis_key=redis_key, input_fields=validated_fields,
                      ghl_contact_id=validated_fields['ghl_contact_id'])
            return JSONResponse(content={"message": "Response queued", "ghl_contact_id": validated_fields['ghl_contact_id']}, status_code=200)

        else:
            await log("error", f"Trigger Response --- Failed to queue --- {validated_fields['ghl_contact_id']}",
                      scope="Trigger Response", redis_key=redis_key, input_fields=validated_fields,
                      ghl_contact_id=validated_fields['ghl_contact_id'])
            return JSONResponse(content={"message": "Failed to queue", "ghl_contact_id": validated_fields['ghl_contact_id']}, status_code=200)

    except Exception as e:
        await log("error", f"Trigger Response: Unexpected error: {str(e)}", scope="Trigger Response", traceback=traceback.format_exc())
        return JSONResponse(content={"error": "Internal code error"}, status_code=500)











@app.post("/testEndpoint")
async def test_endpoint(request: Request):
    try:
        # Get API key and data
        api_key = request.headers.get("x-api-key")
        data = await request.json()
        
        # Log the incoming request
        await log("info", "Test endpoint request", 
                 scope="Test Endpoint", 
                 api_key=api_key,
                 request_data=data)

        # Check if API key exists
        if not api_key:
            return JSONResponse(content={"result": "Invalid", "reason": "Missing API key"}, status_code=200)
            
        # Verify API key
        auth_result = await authenticate(api_key)
        if not auth_result:
            return JSONResponse(content={"result": "Invalid"}, status_code=200)
            
        return JSONResponse(content={"result": "Valid"}, status_code=200)

    except Exception as e:
        await log("error", "Test endpoint error", 
                 scope="Test Endpoint",
                 error=str(e),
                 traceback=traceback.format_exc())
        return JSONResponse(content={"result": str(e)}, status_code=200)
