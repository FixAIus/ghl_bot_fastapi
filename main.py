import redis

redis_url = os.getenv("REDIS_URL")
redis_client = Redis.from_url(redis_url, decode_responses=True)

def listen_to_keyspace():
    """Listen for Redis keyspace notifications and log received data."""
    # Subscribe to keyspace notifications
    pubsub = redis_client.pubsub()
    pubsub.psubscribe("__keyevent@0__:expired")

    log("info", "Subscribed to keyspace notifications")

    # Listen for messages
    for message in pubsub.listen():
        if message["type"] == "pmessage":
            log("info", "Keyspace notif received", data=message)

if __name__ == "__main__":
    # Enable keyspace notifications in Redis (ensure this is set)
    #redis_client.config_set("notify-keyspace-events", "Ex")
    #log("info", "just ran config_set()")
    listen_to_keyspace()
