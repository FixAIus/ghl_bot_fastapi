import traceback
import json
import os
from openai import AsyncOpenAI
import httpx
import asyncio


openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def log(level, msg, **kwargs):
    """Centralized logger for structured JSON logging."""
    print(json.dumps({"level": level, "msg": msg, **kwargs}))


async def KILL_BOT(reason, ghl_contact_id, actions):
    """Kill Bot function to execute specified actions and log results."""
    failed_actions = []

    for action, retries in actions:
        success = False
        for _ in range(retries):
            try:
                result = await action()
                if result is not None:
                    success = True
                    break
            except Exception:
                continue

        if not success:
            # Extracting action name for lambdas
            action_name = action.__name__ if hasattr(action, "__name__") else "some <lambda> shit"
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







async def advance_convo(convo_data):
    try:
        """Main function to advance the conversation."""
        ghl_contact_id = convo_data.get("ghl_contact_id")
        ghl_convo_id = convo_data.get("ghl_convo_id")
        thread_id = convo_data.get("thread_id")
        assistant_id = convo_data.get("assistant_id")
        recent_automated_message_id = convo_data.get("recent_automated_message_id")

        # Compile messages
        messages = await compile_messages(ghl_contact_id, ghl_convo_id, recent_automated_message_id)
        if not messages:
            await KILL_BOT(
                "Bot Failure", 
                ghl_contact_id, 
                [
                    (lambda: ghl_api.remove_tags(ghl_contact_id, ["bott"]), 1),
                    (lambda: ghl_api.add_tags(ghl_contact_id, ["bot failure"]), 1)
                ]
            )
            return

        # Run AI thread
        run_response = await openai_client.beta.threads.runs.create_and_poll(
            thread_id=thread_id,
            assistant_id=assistant_id,
            additional_messages=messages
        )
        if not run_response:
            await KILL_BOT(
                "Bot Failure", 
                ghl_contact_id, 
                [
                    (lambda: ghl_api.remove_tags(ghl_contact_id, ["bott"]), 1),
                    (lambda: ghl_api.add_tags(ghl_contact_id, ["bot failure"]), 1)
                ]
            )
            return

        # Process AI response
        await process_run_response(run_response, thread_id, ghl_contact_id)

    except Exception as e:
        await log("error", "Advance Convo Failed", ghl_contact_id=ghl_contact_id, error=str(e), traceback=traceback.format_exc())


async def compile_messages(ghl_contact_id, ghl_convo_id, recent_automated_message_id):
    try:
        """Fetch and compile messages for processing."""
        all_messages = await ghl_api.retrieve_messages(ghl_contact_id, ghl_convo_id)        

        if all_messages:
            new_messages = []
            found_recent = False
            for msg in all_messages:
                if msg["id"] == recent_automated_message_id:
                    found_recent = True
                    break
                if msg["direction"] == "inbound":
                    new_messages.insert(0, {"role": "user", "content": msg["body"]})
            if found_recent and new_messages:
                await log("info", f"Compile Messages -- Success -- {ghl_contact_id}", ghl_contact_id=ghl_contact_id, compiled_messages=new_messages, all_messages=all_messages)
                return new_messages
                
            await log("error", f"Compile Messages -- No message identifier found or no new messages-- {ghl_contact_id}", ghl_contact_id=ghl_contact_id, 
                      all_messages=all_messages, msg_id=recent_automated_message_id)
        return None
        
    except Exception as e:
        await log("error", "Compile Messages Failed", ghl_contact_id=ghl_contact_id, error=str(e), traceback=traceback.format_exc())


async def process_run_response(run_response, thread_id, ghl_contact_id):
    try:
        """Handle AI response and execute actions."""
        run_status = run_response.status
        run_id = run_response.id

        if run_status == "completed":
            result = await process_message_run(run_id, thread_id, ghl_contact_id)
            if result is None:
                raise Exception("process_message_run returned None")

        elif run_status == "requires_action":
            result = await process_function_run(run_response, thread_id, run_id, ghl_contact_id)
            if result is None:
                raise Exception("process_function_run returned None")

        else:
            await log("error", f"Run Thread -- Run failed -- {ghl_contact_id}", ghl_contact_id=ghl_contact_id, run_response=run_response)
            raise Exception("Run Thread status indicates failure")

    except Exception as e:
        await KILL_BOT(
            "Bot Failure", 
            ghl_contact_id, 
            [
                (lambda: ghl_api.remove_tags(ghl_contact_id, ["bott"]), 1),
                (lambda: ghl_api.add_tags(ghl_contact_id, ["bot failure"]), 1)
            ]
        )
        await log("error", "Process run response failed", ghl_contact_id=ghl_contact_id, error=str(e), traceback=traceback.format_exc())


async def process_message_run(run_id, thread_id, ghl_contact_id):
    """Process the AI message run and send the response to the user."""
    try:
        ai_messages = await openai_client.beta.threads.messages.list(thread_id=thread_id, run_id=run_id)
        ai_messages = ai_messages.data
        if not ai_messages:
            await log("error", f"AI Message -- Get message failed -- {ghl_contact_id}", 
                      scope="AI Message", run_id=run_id, thread_id=thread_id, 
                      response=ai_messages, ghl_contact_id=ghl_contact_id)
            return None

        ai_content = ai_messages[-1].content[0].text.value
        if "【" in ai_content and "】" in ai_content:
            ai_content = ai_content[:ai_content.find("【")] + ai_content[ai_content.find("】") + 1:]

        # Send message via GHL API
        response = await ghl_api.send_message(message=ai_content, contact_id=ghl_contact_id)
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
        await ghl_api.update_contact(ghl_contact_id, update_data)

        await log("info", "AI Message processed and sent", ghl_contact_id=ghl_contact_id, new_automated_message_id=message_id)
        return True

    except Exception as e:
        await log("error", "Process message run failed", ghl_contact_id=ghl_contact_id, error=str(e), traceback=traceback.format_exc())
        return None


async def process_function_run(run_response, thread_id, run_id, ghl_contact_id):
    """Process the function run based on the key in function arguments."""
    try:
        tool_call = run_response.required_action.submit_tool_outputs.tool_calls[0]
        function_args = json.loads(tool_call.function.arguments)

        if "handoff" in function_args:
            await handoff_action(ghl_contact_id)
        elif "reason" in function_args:
            await end_action(ghl_contact_id)
        elif "tier" in function_args:
            await tier1_action(ghl_contact_id)
        else:
            await log("error", "Unhandled function key", ghl_contact_id=ghl_contact_id, key=list(function_args.keys())[0])
            return None

        await openai_client.beta.threads.runs.submit_tool_outputs( 
            thread_id=thread_id,
            run_id=run_id,
            tool_outputs=[{"tool_call_id": tool_call.id, "output": "success"}]
        )

        return True

    except Exception as e:
        await log("error", "Process Function Run Failed", ghl_contact_id=ghl_contact_id, error=str(e), traceback=traceback.format_exc())
        return None


async def handoff_action(ghl_contact_id):
    """Handle handoff logic."""
    await KILL_BOT(
        "Handoff Action", 
        ghl_contact_id, 
        [
            (lambda: ghl_api.remove_tags(ghl_contact_id, ["bott"]), 1),
            (lambda: ghl_api.send_message("ghl_contact_id", "handoff"), 0)
        ]
    )


async def end_action(ghl_contact_id):
    """Handle conversation end logic."""
    await KILL_BOT(
        "End Action", 
        ghl_contact_id, 
        [
            (lambda: ghl_api.remove_tags(ghl_contact_id, ["bott"]), 1),
            (lambda: ghl_api.send_message(ghl_contact_id, "force end"), 0)
        ]
    )


async def tier1_action(ghl_contact_id):
    """Handle Tier 1 response logic."""
    await KILL_BOT(
        "Tier 1 Action", 
        ghl_contact_id, 
        [
            (lambda: ghl_api.remove_tags(ghl_contact_id, ["bott"]), 1),
            (lambda: ghl_api.send_message(ghl_contact_id, "tier 1"), 0)
        ]
    )












### GHL API Class

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
                await log("error", "Get convo ID API call failed", contact_id=contact_id,
                          status_code=response.status_code, response=response.text)
                return None

            conversations = response.json().get("conversations", [])
            if not conversations:
                await log("error", "No Convo ID found", ghl_contact_id=contact_id, response=response.text)
                return None

            return conversations[0].get("id")
        except Exception as e:
            await log("error", f"Unexpected error during GoHighLevelAPI: {str(e)}", scope="get_conversation_id", ghl_contact_id=contact_id, traceback=traceback.format_exc())
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
        except Exception as e:
            await log("error", f"Unexpected error during GoHighLevelAPI: {str(e)}", scope="retrieve_messages", ghl_contact_id=contact_id, traceback=traceback.format_exc())
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
                await log("error", "Update Contact -- API Call Failed", ghl_contact_id=contact_id,
                          status_code=response.status_code, response=response.text)
                return None

            return response.json()
        except Exception as e:
            await log("error", f"Unexpected error during GoHighLevelAPI: {str(e)}", scope="update_contact", ghl_contact_id=contact_id, traceback=traceback.format_exc())
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
                await log("error", "Send Message -- API Call Failed", ghl_contact_id=contact_id,
                          status_code=response.status_code, response=response.text)
                return None

            return response.json()
        except Exception as e:
            await log("error", f"Unexpected error during GoHighLevelAPI: {str(e)}", scope="send_message", ghl_contact_id=contact_id, traceback=traceback.format_exc())
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
                await log("error", "Remove Tags -- API Call Failed", ghl_contact_id=contact_id,
                          tags=tags, status_code=response.status_code, response=response.text)
                return None

            response_tags = response.json().get("tags", [])
            if any(tag in response_tags for tag in tags):
                await log("error", "Remove Tags -- Some tags still present", ghl_contact_id=contact_id,
                          tags=tags, response_tags=response_tags)
                return None

            return response.json()
        except Exception as e:
            await log("error", f"Unexpected error during GoHighLevelAPI: {str(e)}", scope="remove_tags", ghl_contact_id=contact_id, traceback=traceback.format_exc())
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
                await log("error", "Add Tags -- API Call Failed", ghl_contact_id=contact_id,
                          tags=tags, status_code=response.status_code, response=response.text)
                return None

            response_tags = response.json().get("tags", [])
            if not all(tag in response_tags for tag in tags):
                await log("error", "Add Tags -- Not all tags added", ghl_contact_id=contact_id,
                          tags=tags, response_tags=response_tags)
                return None

            return response.json()
        except Exception as e:
            await log("error", f"Unexpected error during GoHighLevelAPI: {str(e)}", scope="add_tags", ghl_contact_id=contact_id, traceback=traceback.format_exc())
            return None




#
#
ghl_api = GoHighLevelAPI()
#
#


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
        await log("error", "GHL Access -- Failed to fetch token",
                  scope="GHL Access", status_code=response.status_code,
                  response=response.text)
    except Exception as e:
        await log("error", "GHL Access -- Request failed",
                  scope="GHL Access", error=str(e),
                  traceback=traceback.format_exc())
    return None
