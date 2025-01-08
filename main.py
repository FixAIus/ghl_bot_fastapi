from redis import Redis
import os
import json

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
                move_convo_forward(data)
            except json.JSONDecodeError as e:
                log("error", "Failed to decode expired key as JSON", error=str(e), raw_data=message["data"])

if __name__ == "__main__":
    listen_to_keyspace()
