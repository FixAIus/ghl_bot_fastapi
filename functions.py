import os
import aiohttp
import json
import traceback
from openai import AsyncOpenAI
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Load environment variables first
load_dotenv()

# Initialize OpenAI client after environment check
def get_openai_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is not set")
    return AsyncOpenAI(api_key=api_key)

# Create client after environment check
openai_client = get_openai_client()


async def fetch_ghl_access_token():
    """Fetch current GHL access token."""
    token = os.getenv("GHL_ACCESS")
    if not token:
        await log("error", "GHL Access -- Token not found in environment", 
            scope="GHL Access")
        return None
    return token


class GHLResponseObject:
    def __init__(self):
        """Initialize empty response schema."""
        self.schema = {
            "response_type": None,
            "action": None,
            "message": None
        }
    
    def add_message(self, message):
        """
        Args:
            message (str): Message content to add
        """
        self.schema["message"] = message
        if self.schema["response_type"] == "action":
            self.schema["response_type"] = "message_action"
        elif not self.schema["response_type"]:
            self.schema["response_type"] = "message"
    
    def add_action(self, action_type, details=None):
        """
        Args:
            action_type (str): Type of action ('force end', 'handoff', 'add_contact_id', etc.)
            details (dict, optional): Additional action details
        """
        self.schema["action"] = {
            "type": action_type,
            "details": details or {}
        }
        if self.schema["response_type"] == "message":
            self.schema["response_type"] = "message_action"
        elif not self.schema["response_type"]:
            self.schema["response_type"] = "action"
    
    def get_response(self):
        """Return the final response schema, removing any None values."""
        return {k: v for k, v in self.schema.items() if v is not None}


async def log(level, msg, **kwargs):
    """Centralized logger for structured JSON logging."""
    print(json.dumps({"level": level, "msg": msg, **kwargs}))


async def validate_request_data(data):
    """Async version of validate_request_data."""
    required_fields = ["thread_id", "assistant_id", "ghl_contact_id", "ghl_recent_message"]
    fields = {field: data.get(field) for field in required_fields}
    fields["ghl_convo_id"] = data.get("ghl_convo_id")
    fields["add_convo_id_action"] = False

    missing_fields = [field for field in required_fields if not fields[field] or fields[field] in ["", "null", None]]
    if missing_fields:
        await log("error", f"Validation -- Missing {', '.join(missing_fields)} -- {fields['ghl_contact_id']}",
            ghl_contact_id=fields["ghl_contact_id"], scope="Validation", received_fields=fields)
        return None

    if not fields["ghl_convo_id"] or fields["ghl_convo_id"] in ["", "null"]:
        fields["ghl_convo_id"] = await get_conversation_id(fields["ghl_contact_id"])
        if not fields["ghl_convo_id"]:
            return None
        fields["add_convo_id_action"] = True

    await log("info", f"Validation -- Fields Received -- {fields['ghl_contact_id']}", scope="Validation", **fields)
    return fields


async def get_conversation_id(ghl_contact_id):
    """Retrieve conversation ID from GHL API."""
    token = await fetch_ghl_access_token()
    if not token:
        return None

    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://services.leadconnectorhq.com/conversations/search",
            headers={
                "Authorization": f"Bearer {token}",
                "Version": "2021-04-15",
                "Accept": "application/json"
            },
            params={"contactId": ghl_contact_id}
        ) as response:
            if response.status != 200:
                await log("error", f"Validation -- Get convo ID API call failed -- {ghl_contact_id}", 
                    scope="Validation", status_code=response.status, 
                    response=await response.text(), ghl_contact_id=ghl_contact_id)
                return None

            data = await response.json()
            conversations = data.get("conversations", [])
            if not conversations:
                await log("error", f"Validation -- No Convo ID found -- {ghl_contact_id}", 
                    scope="Validation", response=data, ghl_contact_id=ghl_contact_id)
                return None
            
            return conversations[0].get("id")


async def retrieve_and_compile_messages(ghl_convo_id, ghl_recent_message, ghl_contact_id):
    """Async version of retrieve_and_compile_messages."""
    token = await fetch_ghl_access_token()
    if not token:
        await log("error", f"Compile Messages -- Token fetch failed -- {ghl_contact_id}", 
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
        ) as response:
            if response.status != 200:
                await log("error", f"Compile Messages -- API Call Failed -- {ghl_contact_id}", 
                    scope="Compile Messages", ghl_contact_id=ghl_contact_id,
                    status_code=response.status, response=await response.text())
                return []

            data = await response.json()
            all_messages = data.get("messages", {}).get("messages", [])
            if not all_messages:
                await log("error", f"Compile Messages -- No messages found -- {ghl_contact_id}", 
                    scope="Compile Messages", api_response=data)
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

            return new_messages[::-1]


async def run_ai_thread(thread_id, assistant_id, messages, ghl_contact_id):
    """Async version of run_ai_thread."""
    try:
        run = await openai_client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=assistant_id,
            additional_messages=messages
        )
        
        while True:
            run = await openai_client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run.id
            )
            if run.status in ['completed', 'requires_action', 'failed']:
                break
            await asyncio.sleep(1)
            
        return run, run.status, run.id
    except Exception as e:
        await log("error", f"AI Run -- API call failed -- {ghl_contact_id}",
            scope="AI Run", error=str(e), traceback=traceback.format_exc())
        raise


async def process_message_response(thread_id, run_id, ghl_contact_id):
    """Async version of process_message_response."""
    messages = await openai_client.beta.threads.messages.list(
        thread_id=thread_id,
        run_id=run_id
    )
    
    if not messages.data:
        await log("error", f"AI Message -- Get message failed -- {ghl_contact_id}", 
            scope="AI Message", run_id=run_id, thread_id=thread_id, 
            response=messages, ghl_contact_id=ghl_contact_id)
        return None

    ai_content = messages.data[-1].content[0].text.value
    if "【" in ai_content and "】" in ai_content:
        ai_content = ai_content[:ai_content.find("【")] + ai_content[ai_content.find("】") + 1:]
    
    return ai_content


async def process_function_response(thread_id, run_id, run_response, ghl_contact_id):
    """Async version of process_function_response."""
    tool_call = run_response.required_action.submit_tool_outputs.tool_calls[0]
    function_args = json.loads(tool_call.function.arguments)
    
    await openai_client.beta.threads.runs.submit_tool_outputs(
        thread_id=thread_id,
        run_id=run_id,
        tool_outputs=[{"tool_call_id": tool_call.id, "output": "success"}]
    )

    action = "handoff" if "handoff" in function_args else "stop"
    
    await log("info", f"AI Function -- Processed function call -- {ghl_contact_id}", 
        scope="AI Function", tool_call_id=tool_call.id, run_id=run_id, 
        thread_id=thread_id, function=function_args, selected_action=action, 
        ghl_contact_id=ghl_contact_id)
    
    return action
