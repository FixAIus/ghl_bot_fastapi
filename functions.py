from redis.asyncio import Redis
from openai import AsyncOpenAI
import os
import json
import traceback
import httpx
import asyncio


async def log(level, msg, **kwargs):
    """Centralized logger for structured JSON logging."""
    print(json.dumps({"level": level, "msg": msg, **kwargs}))


async def KILL_BOT(reason, ghl_contact_id, actions):
    """Kill Bot function to execute specified actions and log results."""
    failed_actions = []

    for action, args, kwargs, retries in actions:
        success = False
        for _ in range(retries):
            try:
                result = await action(*args, **kwargs)
                if result is not None:
                    success = True
                    break
            except Exception:
                continue

        if not success:
            # Extracting action name
            action_name = action.__name__ if hasattr(action, "__name__") else "<unknown>"
            failed_actions.append(action_name)

    result = "all actions successful" if not failed_actions else "some actions failed"
    log_level = "info" if not failed_actions else "error"
    await log(
        log_level, 
        f"Kill Bot -- {reason} -- {result}",
        scope="Kill Bot", 
        ghl_contact_id=ghl_contact_id, 
        failed_actions=failed_actions or None
    )





def make_redis_json_str(input_json):
    """Format the input JSON into a consistent key format."""
    fields_order = [
        "ghl_contact_id",
        "ghl_convo_id",
        "recent_automated_message_id",
        "thread_id",
        "assistant_id",
        "bot_filter_tag"
    ]
    ordered_data = {field: input_json[field] for field in fields_order}
    formatted_string = json.dumps(ordered_data, separators=(",", ":"), sort_keys=False)

    return formatted_string



async def validate_request_data(data):
    """Returns validated fields dictionary or None if validation fails."""
    try:
        required_fields = ["thread_id", "assistant_id", "ghl_contact_id", "recent_automated_message_id", "ghl_convo_id", "bot_filter_tag"]
        fields = {field: data.get(field) for field in required_fields}
        missing_fields = [field for field in required_fields if not fields[field] or fields[field] in ["", "null", None]]
        if missing_fields:
            await log("error", f"Trigger Response -- Missing {', '.join(missing_fields)} -- Canceling Bot",
                      ghl_contact_id=fields.get("ghl_contact_id"), scope="Trigger Response", received_fields=fields)
            return None
        return fields
    except Exception as e:
        await log("error", f"Validate Fields -- Unexpected error: {str(e)}", scope="Trigger Response", traceback=traceback.format_exc())
        return None








class GoHighLevelAPI:
    BASE_URL = "https://services.leadconnectorhq.com"
    HEADERS = {
        "Version": "2021-04-15",
        "Accept": "application/json"
    }

    def __init__(self, location_id=os.getenv('GHL_LOCATION_ID')):
        self.location_id = location_id

    async def get_conversation_id(self, contact_id):
        """Retrieve conversation ID from GHL API."""
        try:
            token = await fetch_ghl_access_token()
            if not token:
                return None

            url = f"{self.BASE_URL}/conversations/search"
            headers = {**self.HEADERS, "Authorization": f"Bearer {token}"}
            params = {"locationId": self.location_id, "contactId": contact_id}

            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, params=params)

            if response.status_code // 100 != 2:
                await log("error", f"GHL API -- get_conversation_id API call failed -- {contact_id}", ghl_contact_id=contact_id,
                          status_code=response.status_code, response=response.text)
                return None

            conversations = response.json().get("conversations", [])
            if not conversations:
                await log("error", f"GHL API -- get_conversation_id No convo ID found -- {contact_id}", ghl_contact_id=contact_id, response=response.text)
                return None

            return conversations[0].get("id")
        except Exception as e:
            await log("error", f"GHL API -- get_conversation_id Unexpected error: {str(e)} -- {contact_id}", ghl_contact_id=contact_id, traceback=traceback.format_exc())
            return None

    async def retrieve_messages(self, contact_id, convo_id, limit=10, type="TYPE_INSTAGRAM"):
        """Retrieve messages from GHL API."""
        try:
            token = await fetch_ghl_access_token()
            if not token:
                return []

            url = f"{self.BASE_URL}/conversations/{convo_id}/messages"
            headers = {**self.HEADERS, "Authorization": f"Bearer {token}"}
            params = {"limit": limit, "type": type}

            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, params=params)

            if response.status_code // 100 != 2:
                await log("error", f"GHL API -- retrieve_messages API Failed -- {contact_id}",
                          ghl_contact_id=contact_id, convo_id=convo_id,
                          status_code=response.status_code, response=response.text)
                return []

            messages = response.json().get("messages", {}).get("messages", [])
            if not messages:
                await log("error", f"GHL API -- retrieve_messages No messages retrieved -- {contact_id}", ghl_contact_id=contact_id,
                          convo_id=convo_id, api_response=response.json())
                return []

            return messages
        except Exception as e:
            await log("error", f"GHL API -- retrieve_messages Unexpected error: {str(e)} -- {contact_id}", ghl_contact_id=contact_id, traceback=traceback.format_exc())
            return []

    async def update_contact(self, contact_id, update_data):
        """Update contact information in GHL API."""
        try:
            token = await fetch_ghl_access_token()
            if not token:
                return None

            url = f"{self.BASE_URL}/contacts/{contact_id}"
            headers = {**self.HEADERS, "Authorization": f"Bearer {token}"}

            async with httpx.AsyncClient() as client:
                response = await client.put(url, headers=headers, json=update_data)

            if response.status_code // 100 != 2 or not response.json().get("succeded"):
                await log("error", f"GHL API -- update_contact API failed -- {contact_id}", ghl_contact_id=contact_id,
                          status_code=response.status_code, response=response.text)
                return None

            return response.json()
        except Exception as e:
            await log("error", f"GHL API -- update_contact Unexpected error: {str(e)} -- {contact_id}", ghl_contact_id=contact_id, traceback=traceback.format_exc())
            return None

    async def send_message(self, contact_id, message, attachments=[], type="IG"):
        """Send a message to a user via GHL API."""
        try:
            token = await fetch_ghl_access_token()
            if not token:
                return None

            url = f"{self.BASE_URL}/conversations/messages"
            headers = {**self.HEADERS, "Authorization": f"Bearer {token}"}
            payload = {
                "locationId": self.location_id,
                "contactId": contact_id,
                "message": message,
                "attachments": attachments,
                "type": type
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=payload)

            if response.status_code // 100 != 2 or not response.json().get("messageId"):
                await log("error", f"GHL API -- send_message API call failed -- {contact_id}", ghl_contact_id=contact_id,
                          status_code=response.status_code, response=response.text)
                return None

            return response.json()
        except Exception as e:
            await log("error", f"GHL API -- send_message Unexpected error: {str(e)} -- {contact_id}", ghl_contact_id=contact_id, traceback=traceback.format_exc())
            return None

    async def remove_tags(self, contact_id, tags):
        """Remove tags from a contact in GHL API."""
        try:
            token = await fetch_ghl_access_token()
            if not token:
                return None

            url = f"{self.BASE_URL}/contacts/{contact_id}/tags"
            headers = {**self.HEADERS, "Authorization": f"Bearer {token}"}
            payload = {
                "tags": tags
            }

            async with httpx.AsyncClient() as client:
                response = await client.request("DELETE", url, headers=headers, json=payload)

            if response.status_code // 100 != 2:
                await log("error", f"GHL API -- remove_tags API call failed -- {contact_id}", ghl_contact_id=contact_id,
                          tags=tags, status_code=response.status_code, response=response.text)
                return None

            response_tags = response.json().get("tags", [])
            if any(tag.lower() in response_tags for tag in tags):
                await log("error", f"GHL API -- remove_tags Some tags still present -- {contact_id}", ghl_contact_id=contact_id,
                          tags=tags, response_tags=response_tags)
                return None

            return response.json()
        except Exception as e:
            await log("error", f"GHL API -- remove_tags Unexpected error: {str(e)} -- {contact_id}", ghl_contact_id=contact_id, traceback=traceback.format_exc())
            return None

    async def add_tags(self, contact_id, tags):
        """Add tags to a contact in GHL API."""
        try:
            token = await fetch_ghl_access_token()
            if not token:
                return None

            url = f"{self.BASE_URL}/contacts/{contact_id}/tags"
            headers = {**self.HEADERS, "Authorization": f"Bearer {token}"}
            payload = {
                "tags": tags
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=payload)

            if response.status_code // 100 != 2:
                await log("error", f"GHL API -- add_tags API call failed -- {contact_id}", ghl_contact_id=contact_id,
                          tags=tags, status_code=response.status_code, response=response.text)
                return None

            response_tags = response.json().get("tags", [])
            if not all(tag.lower() in response_tags for tag in tags):
                await log("error", f"GHL API -- add_tags Not all tags added -- {contact_id}", ghl_contact_id=contact_id,
                          tags=tags, response_tags=response_tags)
                return None

            return response.json()
        except Exception as e:
            await log("error", f"GHL API -- add_tags Unexpected error: {str(e)} -- {contact_id}", ghl_contact_id=contact_id, traceback=traceback.format_exc())
            return None


async def fetch_ghl_access_token():
    """Fetch current GHL access token from Railway."""
    try:
        query = f"""
        query {{
          variables(
            projectId: "{os.getenv('RAILWAY_PROJECT_ID')}"
            environmentId: "{os.getenv('RAILWAY_ENVIRONMENT_ID')}"
            serviceId: "{os.getenv('RAILWAY_SERVICE_ID')}"
          )
        }}
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://backboard.railway.app/graphql/v2",
                headers={
                    "Authorization": f"Bearer {os.getenv('RAILWAY_API_TOKEN')}",
                    "Content-Type": "application/json"
                },
                json={"query": query}
            )

        if response.status_code == 200:
            response_data = response.json()
            if response_data and 'data' in response_data and response_data['data']:
                variables = response_data['data'].get('variables', {})
                if variables and 'GHL_ACCESS' in variables:
                    return variables['GHL_ACCESS']
        await log("error", "Fetch GHL Token -- Railway API Failed",
                  scope="GHL Token", status_code=response.status_code,
                  response=response.text)
    except Exception as e:
        await log("error", "Fetch GHL Token -- Code error",
                  scope="GHL Token", error=str(e),
                  traceback=traceback.format_exc())
    return None
