import os
import json
import traceback
from openai import AsyncOpenAI
import aiohttp

def log(level, msg, **kwargs):
    """Logging function remains synchronous"""
    print(json.dumps({"level": level, "msg": msg, **kwargs}))

def check_environment_variables():
    """Check and log status of required environment variables"""
    required_vars = [
        'RAILWAY_PROJECT_ID',
        'RAILWAY_ENVIRONMENT_ID',
        'RAILWAY_SERVICE_ID',
        'RAILWAY_API_TOKEN',
        'GHL_LOCATION_ID',
        'OPENAI_API_KEY'
    ]
    
    env_status = {}
    for var in required_vars:
        value = os.getenv(var)
        env_status[var] = {
            'present': bool(value),
            'length': len(value) if value else 0
        }
    
    log("info", "Environment Variables Status", **env_status)
    return all(env_status[var]['present'] for var in required_vars)

check_environment_variables()

# Check OpenAI API key after log function is defined
api_key = os.getenv("OPENAI_API_KEY")
log("info", "OpenAI API Key Status", 
    has_key=bool(api_key), 
    key_length=len(api_key) if api_key else 0)

# Initialize async OpenAI client
openai_client = AsyncOpenAI(api_key=api_key)

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
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://backboard.railway.app/graphql/v2",
                headers={
                    "Authorization": f"Bearer {os.getenv('RAILWAY_API_TOKEN')}", 
                    "Content-Type": "application/json"
                },
                json={"query": query}
            ) as response:
                response_text = await response.text()
                
                if response.status == 200:
                    try:
                        response_data = await response.json()
                        if response_data and 'data' in response_data and response_data['data']:
                            variables = response_data['data'].get('variables', {})
                            if variables and 'GHL_ACCESS' in variables:
                                token = variables['GHL_ACCESS']
                                # Validate token format
                                if token and len(token) > 20:  # Basic validation
                                    log("info", "Successfully retrieved GHL token",
                                        token_length=len(token))
                                    return token
                                else:
                                    log("error", "Retrieved invalid GHL token",
                                        token_length=len(token) if token else 0)
                            else:
                                log("error", "GHL_ACCESS not found in variables",
                                    variables=list(variables.keys()) if variables else None)
                        else:
                            log("error", "Invalid response structure from Railway API",
                                response_preview=str(response_data)[:200])
                    except json.JSONDecodeError as e:
                        log("error", "Failed to parse Railway API response",
                            error=str(e),
                            response_preview=response_text[:200])
                else:
                    log("error", "Railway API request failed",
                        status_code=response.status,
                        response=response_text)
                        
    except Exception as e:
        log("error", "GHL Access token fetch failed",
            error=str(e),
            traceback=traceback.format_exc())
    return None

class GHLResponseObject:
    def __init__(self):
        self.schema = {
            "response_type": None,
            "action": None,
            "message": None
        }
    
    def add_message(self, message):
        self.schema["message"] = message
        if self.schema["response_type"] == "action":
            self.schema["response_type"] = "message_action"
        elif not self.schema["response_type"]:
            self.schema["response_type"] = "message"
    
    def add_action(self, action_type, details=None):
        self.schema["action"] = {
            "type": action_type,
            "details": details or {}
        }
        if self.schema["response_type"] == "message":
            self.schema["response_type"] = "message_action"
        elif not self.schema["response_type"]:
            self.schema["response_type"] = "action"
    
    def get_response(self):
        return {k: v for k, v in self.schema.items() if v is not None}

async def validate_request_data(data):
    """Async version of request validation"""
    required_fields = ["thread_id", "assistant_id", "ghl_contact_id", "ghl_recent_message"]
    fields = {field: data.get(field) for field in required_fields}
    fields["ghl_convo_id"] = data.get("ghl_convo_id")
    fields["add_convo_id_action"] = False

    missing_fields = [field for field in required_fields if not fields[field] or fields[field] in ["", "null", None]]
    if missing_fields:
        log("error", f"Validation -- Missing {', '.join(missing_fields)} -- {fields['ghl_contact_id']}",
            ghl_contact_id=fields["ghl_contact_id"], scope="Validation", received_fields=fields)
        return None

    if not fields["ghl_convo_id"] or fields["ghl_convo_id"] in ["", "null"]:
        fields["ghl_convo_id"] = await get_conversation_id(fields["ghl_contact_id"])
        if not fields["ghl_convo_id"]:
            return None
        fields["add_convo_id_action"] = True

    log("info", f"Validation -- Fields Received -- {fields['ghl_contact_id']}", scope="Validation", **fields)
    return fields

async def get_conversation_id(ghl_contact_id):
    """Async version of conversation ID retrieval"""
    token = await fetch_ghl_access_token()
    if not token:
        log("error", "Failed to get valid GHL access token",
            ghl_contact_id=ghl_contact_id)
        return None

    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {token}",
                "Version": "2021-04-15",
                "Accept": "application/json"
            }
            params = {
                "locationId": os.getenv('GHL_LOCATION_ID'),
                "contactId": ghl_contact_id
            }
            
            log("info", "Attempting GHL API call",
                endpoint="conversations/search",
                headers_present=bool(headers),
                params=params)

            async with session.get(
                "https://services.leadconnectorhq.com/conversations/search",
                headers=headers,
                params=params
            ) as search_response:
                response_text = await search_response.text()
                
                if search_response.status != 200:
                    log("error", "GHL API call failed",
                        status_code=search_response.status,
                        response=response_text,
                        ghl_contact_id=ghl_contact_id)
                    return None

                try:
                    response_data = await search_response.json()
                    conversations = response_data.get("conversations", [])
                    
                    if not conversations:
                        log("error", "No conversations found",
                            ghl_contact_id=ghl_contact_id,
                            response_data=response_data)
                        return None
                    
                    convo_id = conversations[0].get("id")
                    if convo_id:
                        log("info", "Successfully retrieved conversation ID",
                            ghl_contact_id=ghl_contact_id,
                            conversation_id=convo_id)
                        return convo_id
                    else:
                        log("error", "Conversation ID missing from response",
                            ghl_contact_id=ghl_contact_id,
                            conversation=conversations[0])
                        return None
                        
                except json.JSONDecodeError as e:
                    log("error", "Failed to parse GHL API response",
                        error=str(e),
                        response_preview=response_text[:200])
                    return None
                    
    except Exception as e:
        log("error", "Unexpected error in get_conversation_id",
            error=str(e),
            traceback=traceback.format_exc(),
            ghl_contact_id=ghl_contact_id)
        return None

async def retrieve_and_compile_messages(ghl_convo_id, ghl_recent_message, ghl_contact_id):
    """Async version of message retrieval and compilation"""
    token = await fetch_ghl_access_token()
    if not token:
        log("error", f"Compile Messages -- Token fetch failed -- {ghl_contact_id}", 
            scope="Compile Messages", ghl_contact_id=ghl_contact_id)
        return []

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"https://services.leadconnectorhq.com/conversations/{ghl_convo_id}/messages",
            headers={
                "Authorization": f"Bearer {token}",
                "Version": "2021-04-15",
                "Accept": "application/json"
            }
        ) as messages_response:
            if messages_response.status != 200:
                log("error", f"Compile Messages -- API Call Failed -- {ghl_contact_id}", 
                    scope="Compile Messages", ghl_contact_id=ghl_contact_id,
                    status_code=messages_response.status, 
                    response=await messages_response.text())
                return []

            response_data = await messages_response.json()
            all_messages = response_data.get("messages", {}).get("messages", [])
            if not all_messages:
                log("error", f"Compile Messages -- No messages found -- {ghl_contact_id}", 
                    scope="Compile Messages", ghl_contact_id=ghl_contact_id,
                    api_response=response_data)
                return []

            new_messages = []
            if any(msg["body"] == ghl_recent_message for msg in all_messages):
                for msg in all_messages:
                    if msg["direction"] == "inbound":
                        new_messages.insert(0, {"role": "user", "content": msg["body"]})
                    if msg["body"] == ghl_recent_message:
                        break
            else:
                new_messages.append({"role": "user", "content": ghl_recent_message})

            log("info", f"Compile Messages -- Successfully compiled -- {ghl_contact_id}", 
                scope="Compile Messages", messages=[msg["content"] for msg in new_messages[::-1]])
            return new_messages[::-1]

async def run_ai_thread(thread_id, assistant_id, messages, ghl_contact_id):
    """Async version of AI thread execution"""
    run_response = await openai_client.beta.threads.runs.create_and_poll(
        thread_id=thread_id,
        assistant_id=assistant_id,
        additional_messages=messages
    )
    run_status, run_id = run_response.status, run_response.id    
    return run_response, run_status, run_id

async def process_message_response(thread_id, run_id, ghl_contact_id):
    """Async version of message response processing"""
    ai_messages = await openai_client.beta.threads.messages.list(thread_id=thread_id, run_id=run_id)
    ai_messages = ai_messages.data
    if not ai_messages:
        log("error", f"AI Message -- Get message failed -- {ghl_contact_id}", 
            scope="AI Message", run_id=run_id, thread_id=thread_id, 
            response=ai_messages, ghl_contact_id=ghl_contact_id)
        return None

    ai_content = ai_messages[-1].content[0].text.value
    if "【" in ai_content and "】" in ai_content:
        ai_content = ai_content[:ai_content.find("【")] + ai_content[ai_content.find("】") + 1:]
    
    log("info", f"AI Message -- Successfully retrieved AI response -- {ghl_contact_id}", 
        scope="AI Message", ai_message=ai_content)
    return ai_content

async def process_function_response(thread_id, run_id, run_response, ghl_contact_id):
    """Async version of function response processing"""
    tool_call = run_response.required_action.submit_tool_outputs.tool_calls[0]
    function_args = json.loads(tool_call.function.arguments)
    
    await openai_client.beta.threads.runs.submit_tool_outputs(
        thread_id=thread_id,
        run_id=run_id,
        tool_outputs=[{"tool_call_id": tool_call.id, "output": "success"}]
    )

    action = "handoff" if "handoff" in function_args else "stop"

    log("info", f"AI Function -- Processed function call -- {ghl_contact_id}", 
        scope="AI Function", tool_call_id=tool_call.id,
        function=function_args, selected_action=action)
    
    return action
