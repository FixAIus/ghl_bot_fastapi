import traceback
from redis import Redis
import os
import json
from openai import OpenAI
from flask import jsonify, request  # For web responses if using Flask


openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def log(level, msg, **kwargs):
    """Centralized logger for structured JSON logging."""
    print(json.dumps({"level": level, "msg": msg, **kwargs}))





import requests
import json
import os
from openai import OpenAI


ghl_api = GoHighLevelAPI()


def compile_messages(ghl_contact_id, ghl_convo_id):
    """Fetch and compile messages for processing."""
    messages = ghl_api.retrieve_messages(ghl_convo_id)
    if not messages:
        log("error", "No messages retrieved from GHL", contact_id=ghl_contact_id)
        return []

    compiled = [{"text": msg["message"], "type": msg["type"]} for msg in messages]
    log("info", "Messages compiled", contact_id=ghl_contact_id, compiled_messages=compiled)
    return compiled

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
        log("error", "AI thread run failed", contact_id=ghl_contact_id, error=str(e))
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

    # Compile messages
    messages = compile_messages(ghl_contact_id, ghl_convo_id)
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

    def __init__(self, location_id):
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

    def retrieve_messages(self, contact_id, limit=50, type="TYPE_INSTAGRAM"):
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

























def move_convo_forward(data):
    """
    Main endpoint for handling conversation flow between user and AI assistant.
    Processes incoming messages and sends appropriate AI responses or function calls.
    """
    try:
        # Initialize GHL API
        ghl_api = GoHighLevelAPI(location_id=os.getenv('GHL_LOCATION_ID'))

        # Extract required fields from the request
        ghl_convo_id = data["ghl_convo_id"]
        ghl_contact_id = data["ghl_contact_id"]
        recent_automated_message_id = data["recent_automated_message_id"]
        thread_id = data["thread_id"]
        assistant_id = data["assistant_id"]

        # Retrieve messages using GHL API
        all_messages = ghl_api.retrieve_messages(contact_id=ghl_contact_id)
        if not all_messages:
            return jsonify({"error": "No messages retrieved"}), 400

        # Compile new messages
        new_messages = []
        for msg in all_messages:
            if msg["direction"] == "inbound":
                new_messages.insert(0, {"role": "user", "content": msg["body"]})
            if msg["id"] == recent_automated_message_id:
                break

        # Run AI thread and get response
        run_response, run_status, run_id = run_ai_thread(
            thread_id=thread_id,
            assistant_id=assistant_id,
            messages=new_messages,
            ghl_contact_id=ghl_contact_id
        )

        # Handle AI response
        if run_status == "completed":
            process_message_response(
                thread_id=thread_id,
                run_id=run_id,
                ghl_contact_id=ghl_contact_id,
                ghl_api=ghl_api
            )

        elif run_status == "requires_action":
            process_function_response(
                thread_id=thread_id,
                run_id=run_id,
                run_response=run_response,
                ghl_contact_id=ghl_contact_id,
                ghl_api=ghl_api
            )

        else:
            log("error", f"AI Run -- Run Failed -- {ghl_contact_id}", 
                scope="AI Run", run_status=run_status, run_id=run_id, 
                thread_id=thread_id, run_response=run_response, ghl_contact_id=ghl_contact_id)
            return jsonify({"error": f"Run {run_status}"}), 400

        # Return success response
        return jsonify({"status": "success"}), 200

    except Exception as e:
        # Capture and log the traceback
        tb_str = traceback.format_exc()
        log("error", "GENERAL -- Unhandled exception occurred with traceback",
            scope="General", error=str(e), traceback=tb_str)
        return jsonify({"error": str(e), "traceback": tb_str}), 500


def run_ai_thread(thread_id, assistant_id, messages, ghl_contact_id):
    """Run AI thread and get initial response."""
    run_response = openai_client.beta.threads.runs.create_and_poll(
        thread_id=thread_id,
        assistant_id=assistant_id,
        additional_messages=messages
    )
    run_status, run_id = run_response.status, run_response.id    
    return run_response, run_status, run_id



def process_function_response(thread_id, run_id, run_response, ghl_contact_id, ghl_api):
    """Process function call response from AI."""
    tool_call = run_response.required_action.submit_tool_outputs.tool_calls[0]
    function_args = json.loads(tool_call.function.arguments)
    openai_client.beta.threads.runs.submit_tool_outputs(
        thread_id=thread_id,
        run_id=run_id,
        tool_outputs=[{"tool_call_id": tool_call.id, "output": "success"}]
    )

    action = "handoff" if "handoff" in function_args else "stop"

    ghl_api.send_message(
        message=f"Action triggered: {action}",
        contact_id=ghl_contact_id
    )

    log("info", f"AI Function -- Processed function call -- {ghl_contact_id}", 
        scope="AI Function", tool_call_id=tool_call.id, run_id=run_id, 
        thread_id=thread_id, function=function_args, selected_action=action, 
        ghl_contact_id=ghl_contact_id)




def process_message_response(thread_id, run_id, ghl_contact_id, ghl_api):
    """Process completed message response from AI."""
    ai_messages = openai_client.beta.threads.messages.list(thread_id=thread_id, run_id=run_id).data
    if not ai_messages:
        log("error", f"AI Message -- Get message failed -- {ghl_contact_id}", 
            scope="AI Message", run_id=run_id, thread_id=thread_id, 
            response=ai_messages, ghl_contact_id=ghl_contact_id)
        return

    ai_content = ai_messages[-1].content[0].text.value
    if "【" in ai_content and "】" in ai_content:
        ai_content = ai_content[:ai_content.find("【")] + ai_content[ai_content.find("】") + 1:]

    ghl_api.send_message(
        message=ai_content,
        contact_id=ghl_contact_id
    )

    log("info", f"AI Message -- Successfully retrieved AI response -- {ghl_contact_id}", 
        scope="AI Message", run_id=run_id, thread_id=thread_id, 
        ai_message=ai_content, ghl_contact_id=ghl_contact_id)



