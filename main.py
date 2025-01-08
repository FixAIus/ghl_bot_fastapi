# Standard Python libraries
import os
import json
import traceback

# External libraries
from redis import Redis  # For Redis connection and keyspace listening
import requests  # For HTTP requests (e.g., fetching GHL tokens)
from flask import jsonify, request  # For web responses if using Flask
from openai import OpenAI  # OpenAI API client

# Imports from functions.py itself
from functions import (
    move_convo_forward,  # The main conversation handler
    log,  # The centralized logger
    GoHighLevelAPI,  # The GHL API wrapper class
    fetch_ghl_access_token,  # Token fetcher
    process_message_response,  # AI message processor
    process_function_response,  # Function call response processor
    run_ai_thread  # AI thread execution
)


redis_url = os.getenv("REDIS_URL")
redis_client = Redis.from_url(redis_url, decode_responses=True)



def listen_to_keyspace():
    """Listen for Redis keyspace notifications and log received data."""
    # Subscribe to keyspace notifications
    pubsub = redis_client.pubsub()
    pubsub.psubscribe("__keyevent@0__:expired")

    log("info", "Listening for keyspace notifications")

    # Listen for messages
    for message in pubsub.listen():
        if message["type"] == "pmessage":
            try:
                expired_key = message["data"]
                json_data = json.loads(expired_key)

                # Log the reconstructed JSON object
                move_convo_forward(json_data)
            except json.JSONDecodeError as e:
                log("error", "Failed to decode expired key as JSON", error=str(e), raw_data=message["data"])

if __name__ == "__main__":
    listen_to_keyspace()
