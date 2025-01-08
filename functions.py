import traceback
import requests
import json
import os
from openai import OpenAI

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
ghl_api = GoHighLevelAPI()



def log(level, msg, **kwargs):
    """Centralized logger for structured JSON logging."""
    print(json.dumps({"level": level, "msg": msg, **kwargs}))



def compile_messages(ghl_contact_id, ghl_convo_id, recent_automated_message_id):
    """Fetch and compile messages for processing."""
    all_messages = ghl_api.retrieve_messages(ghl_convo_id)

    #delete
    log("info", "messages grasped", all_messages=all_messages)
    
    new_messages = []

    for msg in all_messages:
        if msg["id"] == recent_automated_message_id:
            break
        if msg["direction"] == "inbound":
            new_messages.insert(0, {"role": "user", "content": msg["body"]})

    log("info", "Messages compiled", contact_id=ghl_contact_id, compiled_messages=new_messages)
    return new_messages


def run_ai_thread(thread_id, assistant_id, messages, ghl_contact_id):
    """Run the AI thread and retrieve its response."""
    try:
        run_response = openai_client.beta.threads.runs.create_and_poll(
            thread_id=thread_id,
            assistant_id=assistant_id,
            additional_messages=messages
        )
        return run_response, run_response.status, run_response.id
    except Exception as e:
        log("error", "AI thread run failed", contact_id=ghl_contact_id, error=str(e), traceback=traceback.format_exc())
        return None, None, None


def process_run_response(run_response, ghl_contact_id):
    """Handle AI response and execute actions."""
    status = run_response.get("status")

    if status == "completed":
        message_content = run_response.get("message")
        ghl_api.send_message(message_content, ghl_contact_id)

    elif status == "requires_action":
        action = run_response.get("action")

        if action == "handoff":
            handoff_action(ghl_contact_id)
        elif action == "end":
            end_action(ghl_contact_id)
        elif action == "tier 1":
            tier1_action(ghl_contact_id)
        else:
            log("error", "Unknown action required", contact_id=ghl_contact_id, action=action)

    else:
        log("error", "Unhandled response status", contact_id=ghl_contact_id, status=status)


def handoff_action(ghl_contact_id):
    """Handle handoff logic."""
    ghl_api.remove_tag(ghl_contact_id, ["automated_tag"])
    ghl_api.send_message("A team member will assist you shortly.", ghl_contact_id)
    log("info", "Handoff action completed", contact_id=ghl_contact_id)


def end_action(ghl_contact_id):
    """Handle conversation end logic."""
    ghl_api.remove_tag(ghl_contact_id, ["automated_tag"])
    log("info", "Conversation ended", contact_id=ghl_contact_id)


def tier1_action(ghl_contact_id):
    """Handle Tier 1 response logic."""
    ghl_api.send_message("Here is the information for Tier 1 resources.", ghl_contact_id)
    log("info", "Tier 1 action completed", contact_id=ghl_contact_id)


def advance_convo(convo_data):
    """Main function to advance the conversation."""
    ghl_contact_id = convo_data.get("ghl_contact_id")
    ghl_convo_id = convo_data.get("ghl_convo_id")
    thread_id = convo_data.get("thread_id")
    assistant_id = convo_data.get("assistant_id")
    recent_automated_message_id = convo_data.get("recent_automated_message_id")

    # Compile messages
    messages = compile_messages(ghl_contact_id, ghl_convo_id, recent_automated_message_id)
    if not messages:
        log("error", "Message compilation failed", contact_id=ghl_contact_id)
        return

    # Run AI thread
    run_response, status, run_id = run_ai_thread(thread_id, assistant_id, messages, ghl_contact_id)
    if not run_response:
        log("error", "AI thread failed", contact_id=ghl_contact_id)
        return

    # Process AI response
    process_run_response(run_response, ghl_contact_id)







def fetch_ghl_access_token():
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
        response = requests.post(
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
        log("error", f"GHL Access -- Failed to fetch token", 
            scope="GHL Access", status_code=response.status_code, 
            response=response.text)
    except Exception as e:
        log("error", f"GHL Access -- Request failed", 
            scope="GHL Access", error=str(e), 
            traceback=traceback.format_exc())
    return None


class GoHighLevelAPI:
    BASE_URL = "https://services.leadconnectorhq.com"
    HEADERS = {
        "Version": "2021-04-15",
        "Accept": "application/json"
    }

    def __init__(self, location_id=os.getenv('GHL_LOCATION_ID')):
        self.location_id = location_id

    def get_conversation_id(self, contact_id):
        """Retrieve conversation ID from GHL API."""
        token = fetch_ghl_access_token()
        if not token:
            return None

        url = f"{self.BASE_URL}/conversations/search"
        headers = {**self.HEADERS, "Authorization": f"Bearer {token}"}
        params = {"locationId": self.location_id, "contactId": contact_id}

        response = requests.get(url, headers=headers, params=params)
        if not response.status_code // 100 == 2:
            log("error", "Get convo ID API call failed", contact_id=contact_id, \
                status_code=response.status_code, response=response.text)
            return None

        conversations = response.json().get("conversations", [])
        if not conversations:
            log("error", "No Convo ID found", contact_id=contact_id, response=response.text)
            return None

        return conversations[0].get("id")

    def retrieve_messages(self, contact_id, limit=8, type="TYPE_INSTAGRAM"):
        """Retrieve messages from GHL API."""
        token = fetch_ghl_access_token()
        if not token:
            return []

        url = f"{self.BASE_URL}/conversations/{convo_id}/messages"
        headers = {**self.HEADERS, "Authorization": f"Bearer {token}"}
        params = {"limit": limit, "type": type}

        response = requests.get(url, headers=headers, params=params)
        if not response.status_code // 100 == 2:
            log("error", "Retrieve Messages -- API Call Failed", \
                contact_id=contact_id, convo_id=convo_id, \
                status_code=response.status_code, response=response.text)
            return []

        messages = response.json().get("messages", {}).get("messages", [])
        if not messages:
            log("error", "Retrieve Messages -- No messages found", contact_id=contact_id, \
                convo_id=convo_id, api_response=response.json())
            return []

        return messages

    def update_contact(self, contact_id, update_data):
        """Update contact information in GHL API."""
        token = fetch_ghl_access_token()
        if not token:
            return None

        url = f"{self.BASE_URL}/contacts/{contact_id}"
        headers = {**self.HEADERS, "Authorization": f"Bearer {token}"}

        response = requests.put(url, headers=headers, json=update_data)
        if not response.status_code // 100 == 2:
            log("error", "Update Contact -- API Call Failed", contact_id=contact_id, \
                status_code=response.status_code, response=response.text)
            return None

        log("info", "Update Contact -- Successfully updated", contact_id=contact_id, response=response.json())
        return response.json()

    def send_message(self, message, contact_id, attachments=[], type="IG"):
        """Send a message to a user via GHL API."""
        token = fetch_ghl_access_token()
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

        response = requests.post(url, headers=headers, json=payload)
        if not response.status_code // 100 == 2:
            log("error", "Send Message -- API Call Failed", contact_id=contact_id, \
                status_code=response.status_code, response=response.text)
            return None

        log("info", "Send Message -- Successfully sent", contact_id=contact_id, response=response.json())
        return response.json()

    def remove_tag(self, contact_id, tags):
        """Remove tags from a contact in GHL API."""
        token = fetch_ghl_access_token()
        if not token:
            return None

        url = f"{self.BASE_URL}/contacts/{contact_id}/tags"
        headers = {**self.HEADERS, "Authorization": f"Bearer {token}"}
        payload = {
            "tags": tags
        }

        response = requests.delete(url, headers=headers, json=payload)
        if not response.status_code // 100 == 2:
            log("error", "Remove Tag -- API Call Failed", contact_id=contact_id, \
                tags=tags, status_code=response.status_code, response=response.text)
            return None

        log("info", "Remove Tag -- Successfully removed tags", contact_id=contact_id, tags=tags, response=response.json())
        return response.json()










