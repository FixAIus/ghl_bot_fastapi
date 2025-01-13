import traceback
import json
import os
from openai import AsyncOpenAI
import httpx
import asyncio
from redis.asyncio import Redis
from functions import (
    log,
    KILL_BOT,
    ghl_api,
    GoHighLevelAPI,
    openai_client,
    fetch_ghl_access_token,
    advance_convo,
    compile_messages,
    process_run_response,
    process_message_run
)

redis_url = os.getenv("REDIS_URL")
redis_client = Redis.from_url(redis_url, decode_responses=True)


async def listen_to_keyspace():
    """Listen for Redis keyspace notifications and log received data."""    
    # Subscribe to keyspace notifications
    pubsub = redis_client.pubsub()
    await pubsub.psubscribe("__keyevent@0__:expired")
################################################################################################################################################################################
    await log("info", "Listening for keyspace notifications")

    try:
        await log("info", "trying to add"+os.getenv('BDMCOURSE_LINK'))
    except Exception as e:
        await log("info", f"error: {e}")

    await log("info", f"regular try: {os.getenv('BDMCOURSE_LINK')}")
############################################
    # Listen for messages
    async for message in pubsub.listen():
        if message["type"] == "pmessage":
            try:
                expired_key = message["data"]
                json_data = json.loads(expired_key)

                # Log the reconstructed JSON object
                await log("info", f"Advance Convo -- Triggering advance_convo() -- {json_data['ghl_contact_id']}", data=json_data, scope="Advance Convo")
                asyncio.create_task(advance_convo(json_data))

            except json.JSONDecodeError as e:
                await log("error", f"Advance Convo -- Failed to decode trigger info -- {json_data['ghl_contact_id']}",
                          error=str(e), raw_data=message["data"], ghl_contact_id=json_data["ghl_contact_id"])

if __name__ == "__main__":
    asyncio.run(listen_to_keyspace())
