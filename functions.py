import traceback
import requests
import json
import os
from openai import OpenAI

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
            log("error", "Get convo ID API call failed", ghl_contact_id=contact_id, \
                status_code=response.status_code, response=response.text)
            return None

        conversations = response.json().get("conversations", [])
        if not conversations:
            log("error", "No Convo ID found", ghl_contact_id=contact_id, response=response.text)
            return None

        return conversations[0].get("id")

    def retrieve_messages(self, convo_id, contact_id, limit=8, type="TYPE_INSTAGRAM"):
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
                ghl_contact_id=contact_id, convo_id=convo_id, \
                status_code=response.status_code, response=response.text)
            return []

        messages = response.json().get("messages", {}).get("messages", [])
        if not messages:
            log("error", "Retrieve Messages -- No messages found", ghl_contact_id=contact_id, \
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
            log("error", "Update Contact -- API Call Failed", ghl_contact_id=contact_id, \
                status_code=response.status_code, response=response.text)
            return None

        log("info", "Update Contact -- Successfully updated", ghl_contact_id=contact_id, response=response.json())
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
            log("error", "Send Message -- API Call Failed", ghl_contact_id=contact_id, \
                status_code=response.status_code, response=response.text)
            return None

        log("info", "Send Message -- Successfully sent", ghl_contact_id=contact_id, response=response.json())
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
            log("error", "Remove Tag -- API Call Failed", ghl_contact_id=contact_id, \
                tags=tags, status_code=response.status_code, response=response.text)
            return None

        log("info", "Remove Tag -- Successfully removed tags", ghl_contact_id=contact_id, tags=tags, response=response.json())
        return response.json()

    def add_tag(self, contact_id, tags):
        """Add tags to a contact in GHL API."""
        token = fetch_ghl_access_token()
        if not token:
            return None

        url = f"{self.BASE_URL}/contacts/{contact_id}/tags"
        headers = {**self.HEADERS, "Authorization": f"Bearer {token}"}
        payload = {
            "tags": tags
        }

        response = requests.post(url, headers=headers, json=payload)
        if not response.status_code // 100 == 2:
            log("error", "Add Tag -- API Call Failed", ghl_contact_id=contact_id, \
                tags=tags, status_code=response.status_code, response=response.text)
            return None

        log("info", "Add Tag -- Successfully added tags", ghl_contact_id=contact_id, tags=tags, response=response.json())
        return response.json()




openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
ghl_api = GoHighLevelAPI()


def log(level, msg, **kwargs):
    """Centralized logger for structured JSON logging."""
    print(json.dumps({"level": level, "msg": msg, **kwargs}))



def compile_messages(ghl_contact_id, ghl_convo_id, recent_automated_message_id):
    try:
        """Fetch and compile messages for processing."""
        all_messages = ghl_api.retrieve_messages(ghl_convo_id, ghl_contact_id)        

        if all_messages:
            new_messages = []
            found_recent = False
            for msg in all_messages:
                if msg["id"] == recent_automated_message_id:
                    found_recent = True
                    break
                if msg["direction"] == "inbound":
                    new_messages.insert(0, {"role": "user", "content": msg["body"]})
            if found_recent:
                log("info", f"Compile Messages -- Success -- {ghl_contact_id}", ghl_contact_id=ghl_contact_id, compiled_messages=new_messages, all_messages=all_messages)
                return new_messages
                
            log("error", f"Compile Messages -- No message identifier found -- {ghl_contact_id}", ghl_contact_id=ghl_contact_id, 
                all_messages=all_messages, msg_id=recent_automated_message_id)
        return None
        
    except Exception as e:
        log("error", "Compile Messages Failed", ghl_contact_id=ghl_contact_id, error=str(e), traceback=traceback.format_exc())



def process_run_response(run_response, thread_id, ghl_contact_id):
    try:
        """Handle AI response and execute actions."""
        run_status = run_response.status
        run_id = run_response.id
    
        if run_status == "completed":
            process_message_run(run_id, thread_id, ghl_contact_id)
    
        elif run_status == "requires_action":
            process_function_run(run_response, thread_id, run_id, ghl_contact_id)
            
        else:
            log("error", f"Run Thread -- Run failed -- {ghl_contact_id}", ghl_contact_id=ghl_contact_id, run_response=run_response)

    except Exception as e:
        log("error", "Process run response failed", ghl_contact_id=ghl_contact_id, error=str(e), traceback=traceback.format_exc())


def process_message_run(run_id, thread_id, ghl_contact_id):
    """Process the AI message run and send the response to the user."""
    try:
        ai_messages = openai_client.beta.threads.messages.list(thread_id=thread_id, run_id=run_id).data
        if not ai_messages:
            log("error", f"AI Message -- Get message failed -- {ghl_contact_id}", 
                scope="AI Message", run_id=run_id, thread_id=thread_id, 
                response=ai_messages, ghl_contact_id=ghl_contact_id)
            return None

        ai_content = ai_messages[-1].content[0].text.value
        if "【" in ai_content and "】" in ai_content:
            ai_content = ai_content[:ai_content.find("【")] + ai_content[ai_content.find("】") + 1:]

        # Send message via GHL API
        response = ghl_api.send_message(message=ai_content, contact_id=ghl_contact_id)
        if not response:
            return None

        # Update the message ID field
        message_id = response["messageId"]
        update_data = {
            "customFields": [
                {
                    "key": "recent_automated_message_id",
                    "field_value": message_id
                }
            ]
        }
        ghl_api.update_contact(ghl_contact_id, update_data)

        log("info", "AI Message processed and sent", ghl_contact_id=ghl_contact_id, new_automated_message_id=message_id)
        return message_id

    except Exception as e:
        log("error", "Process message run failed", ghl_contact_id=ghl_contact_id, error=str(e), traceback=traceback.format_exc())



def process_function_run(run_response, thread_id, run_id, ghl_contact_id):
    """Process the function run based on the key in function arguments."""
    try:
        tool_call = run_response.required_action.submit_tool_outputs.tool_calls[0]
        function_args = json.loads(tool_call.function.arguments)

        if "handoff" in function_args:
            handoff_action(ghl_contact_id)
        elif "end_conversation" in function_args:
            end_action(ghl_contact_id)
        elif "tier_1_response" in function_args:
            tier1_action(ghl_contact_id)
        else:
            log("error", "Unhandled function key", ghl_contact_id=ghl_contact_id, key=list(function_args.keys())[0])
            return None

        openai_client.beta.threads.runs.submit_tool_outputs( 
            thread_id=thread_id,
            run_id=run_id,
            tool_outputs=[{"tool_call_id": tool_call.id, "output": "success"}]
        )

        log("info", "Function run processed", ghl_contact_id=ghl_contact_id, function_args=function_args)
        return True

    except Exception as e:
        log("error", "Process Function Run Failed", ghl_contact_id=ghl_contact_id, error=str(e), traceback=traceback.format_exc())
        return None


def handoff_action(ghl_contact_id):
    """Handle handoff logic."""
    ghl_api.remove_tag(ghl_contact_id, ["automated_tag"])
    ghl_api.send_message("handoff", ghl_contact_id)
    log("info", "Handoff action completed", ghl_contact_id=ghl_contact_id)


def end_action(ghl_contact_id):
    """Handle conversation end logic."""
    ghl_api.remove_tag(ghl_contact_id, ["automated_tag"])
    ghl_api.send_message("end", ghl_contact_id)
    log("info", "Conversation ended", ghl_contact_id=ghl_contact_id)


def tier1_action(ghl_contact_id):
    """Handle Tier 1 response logic."""
    ghl_api.send_message("tier 1", ghl_contact_id)
    ghl_api.send_message("Here is the information for Tier 1 resources.", ghl_contact_id)
    log("info", "Tier 1 action completed", ghl_contact_id=ghl_contact_id)




def advance_convo(convo_data):
    try:
        """Main function to advance the conversation."""
        ghl_contact_id = convo_data.get("ghl_contact_id")
        ghl_convo_id = convo_data.get("ghl_convo_id")
        thread_id = convo_data.get("thread_id")
        assistant_id = convo_data.get("assistant_id")
        recent_automated_message_id = convo_data.get("recent_automated_message_id")

        # Compile messages
        messages = compile_messages(ghl_contact_id, ghl_convo_id, recent_automated_message_id)
        if not messages:
            return
    
        # Run AI thread
        run_response = openai_client.beta.threads.runs.create_and_poll(
            thread_id=thread_id,
            assistant_id=assistant_id,
            additional_messages=messages
        )
        if not run_response:
            log("error", f"Run Thread -- No run response -- {ghl_contact_id}", ghl_contact_id=ghl_contact_id, run_response=run_response, thread_id=thread_id)
            return
    
        # Process AI response
        process_run_response(run_response, thread_id, ghl_contact_id)

    except Exception as e:
        log("error", "Advance Convo Failed", ghl_contact_id=ghl_contact_id, error=str(e), traceback=traceback.format_exc())







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






