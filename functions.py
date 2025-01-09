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


def make_redis_json_str(input_json):
    """Format the input JSON into a consistent key format."""
    fields_order = [
        "ghl_contact_id",
        "ghl_convo_id",
        "recent_automated_message_id",
        "thread_id",
        "assistant_id",
    ]
    ordered_data = {field: input_json[field] for field in fields_order}
    formatted_string = json.dumps(ordered_data, separators=(",", ":"), sort_keys=False)

    return formatted_string


async def validate_request_data(data):
    """Returns validated fields dictionary or None if validation fails."""
    try:
        required_fields = ["thread_id", "assistant_id", "ghl_contact_id", "recent_automated_message_id", "ghl_convo_id"]
        fields = {field: data.get(field) for field in required_fields}
        missing_fields = [field for field in required_fields if not fields[field] or fields[field] in ["", "null", None]]
        if missing_fields:
            # Insert failure handoff
            await log("error", f"Validation -- Missing {', '.join(missing_fields)} -- Canceling Bot",
                      ghl_contact_id=fields.get("ghl_contact_id"), scope="Redis Queue", received_fields=fields)
            return None
        return fields
    except Exception as e:
        await log("error", f"Unexpected error: {str(e)}", scope="Redis Queue", traceback=traceback.format_exc())
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
        token = await fetch_ghl_access_token()
        if not token:
            return None

        url = f"{self.BASE_URL}/conversations/search"
        headers = {**self.HEADERS, "Authorization": f"Bearer {token}"}
        params = {"locationId": self.location_id, "contactId": contact_id}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)

        if response.status_code // 100 != 2:
            await log("error", "Get convo ID API call failed", contact_id=contact_id,
                      status_code=response.status_code, response=response.text)
            return None

        conversations = response.json().get("conversations", [])
        if not conversations:
            await log("error", "No Convo ID found", ghl_contact_id=contact_id, response=response.text)
            return None

        return conversations[0].get("id")

    async def retrieve_messages(self, convo_id, contact_id, limit=10, type="TYPE_INSTAGRAM"):
        """Retrieve messages from GHL API."""
        token = await fetch_ghl_access_token()
        if not token:
            return []

        url = f"{self.BASE_URL}/conversations/{convo_id}/messages"
        headers = {**self.HEADERS, "Authorization": f"Bearer {token}"}
        params = {"limit": limit, "type": type}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params)

        if response.status_code // 100 != 2:
            await log("error", "Retrieve Messages -- API Call Failed",
                      contact_id=contact_id, convo_id=convo_id,
                      status_code=response.status_code, response=response.text)
            return []

        messages = response.json().get("messages", {}).get("messages", [])
        if not messages:
            await log("error", "Retrieve Messages -- No messages found", ghl_contact_id=contact_id,
                      convo_id=convo_id, api_response=response.json())
            return []

        return messages

    async def update_contact(self, contact_id, update_data):
        """Update contact information in GHL API."""
        token = await fetch_ghl_access_token()
        if not token:
            return None

        url = f"{self.BASE_URL}/contacts/{contact_id}"
        headers = {**self.HEADERS, "Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient() as client:
            response = await client.put(url, headers=headers, json=update_data)

        if response.status_code // 100 != 2 or not response.json()["succeded"]:
            await log("error", "Update Contact -- API Call Failed", ghl_contact_id=contact_id,
                      status_code=response.status_code, response=response.text)
            return None

        return response.json()

    async def send_message(self, message, contact_id, attachments=[], type="IG"):
        """Send a message to a user via GHL API."""
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

        if response.status_code // 100 != 2:
            await log("error", "Send Message -- API Call Failed", ghl_contact_id=contact_id,
                      status_code=response.status_code, response=response.text)
            return None

        return response.json()

    async def remove_tag(self, contact_id, tags):
        """Remove tags from a contact in GHL API."""
        token = await fetch_ghl_access_token()
        if not token:
            return None

        url = f"{self.BASE_URL}/contacts/{contact_id}/tags"
        headers = {**self.HEADERS, "Authorization": f"Bearer {token}"}
        payload = {
            "tags": tags
        }

        async with httpx.AsyncClient() as client:
            response = await client.delete(url, headers=headers, json=payload)

        if response.status_code // 100 != 2:
            await log("error", "Remove Tag -- API Call Failed", ghl_contact_id=contact_id,
                      tags=tags, status_code=response.status_code, response=response.text)
            return None

        return response.json()

    async def add_tag(self, contact_id, tags):
        """Add tags to a contact in GHL API."""
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
            await log("error", "Add Tag -- API Call Failed", ghl_contact_id=contact_id,
                      tags=tags, status_code=response.status_code, response=response.text)
            return None

        return response.json()


async def fetch_ghl_access_token():
    """Fetch current GHL access token from Railway."""
    query = f"""
    query {{
      variables(
        projectId: "{os.getenv('RAILWAY_PROJECT_ID')}"
        environmentId: "{os.getenv('RAILWAY_ENVIRONMENT_ID')}"
        serviceId: "{os.getenv('RAILWAY_SERVICE_ID')}"
      )
    }}
    """
    try:
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
        await log("error", "GHL Access -- Failed to fetch token",
                  scope="GHL Access", status_code=response.status_code,
                  response=response.text)
    except Exception as e:
        await log("error", "GHL Access -- Request failed",
                  scope="GHL Access", error=str(e),
                  traceback=traceback.format_exc())
    return None
