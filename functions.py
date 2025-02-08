import httpx
import json
import asyncio

async def log(level, msg, **kwargs):
    print(json.dumps({"level": level, "msg": msg, **kwargs}))

class AirtableClient:
    def __init__(self, api_key, base_id, table_id):
        self.api_key = api_key
        self.base_id = base_id
        self.table_id = table_id
        self.url_base = "https://api.airtable.com/v0/"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def get_base_schema(self):
        try:
            url = f"{self.url_base}meta/bases/{self.base_id}/tables"
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=self.headers)
            
            if response.status_code == 200:
                return response.json()
            else:
                await log("error", "get_base_schema failed", response=response.json())
                return None
        except Exception as e:
            response_content = None
            try:
                response_content = response.json()
            except:
                response_content = "No response or not JSON format"
            await log("error", "Exception occurred in get_base_schema", exception=str(e), response=response_content)
            return None

    async def create_record(self, fields):
        try:
            url = f"{self.url_base}{self.base_id}/{self.table_id}"
            data = {
                "fields": fields
            }
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=self.headers, json=data)
            
            if response.status_code in [200, 201]:
                return response.json().get('id', None)
            else:
                await log("error", "create_record failed", response=response.json(), fields=fields)
                return None
        except Exception as e:
            response_content = None
            try:
                response_content = response.json()
            except:
                response_content = "No response or not JSON format"
            await log("error", "Exception occurred in create_record", exception=str(e), response=response_content, fields=fields)
            return None

    async def update_record(self, record_id, fields, method='PATCH'):
        try:
            url = f"{self.url_base}{self.base_id}/{self.table_id}/{record_id}"
            data = {
                "fields": fields
            }
            if method not in ['PATCH', 'PUT']:
                raise ValueError("Method must be 'PATCH' or 'PUT'.")

            async with httpx.AsyncClient() as client:
                response = await client.request(method, url, headers=self.headers, json=data)
            
            if response.status_code == 200:
                return response.json()
            else:
                await log("error", "update_record failed", response=response.json(), fields=fields)
                return None
        except Exception as e:
            response_content = None
            try:
                response_content = response.json()
            except:
                response_content = "No response or not JSON format"
            await log("error", "Exception occurred in update_record", exception=str(e), response=response_content, fields=fields)
            return None

# Example usage
async def main():
    # Define your API key, base ID, and table ID here
    api_key = "patMP43xP8KHVfepX.af949fb753d690b61bb9ce7cede5c66f908cbfe0086e0cecf354bd7ccc7077ac"
    base_id = "appqlPGp6IWfdyZMp"
    table_id = "tblD1vQglA9gq73i7"

    airtable_client = AirtableClient(api_key, base_id, table_id)

    try:
        # Create a new record
        fields = {
            "GHL Contact ID": "Value210909",
            "GHL Name": "Value22"
        }
        record_id = await airtable_client.create_record(fields)
        if record_id:
            print(f"Record created with ID: {record_id}")

            # Update the record
            updated_fields = {
                "GHL Contact ID": "NewValjiue21",
                "GHL Name": "NewValue22"
            }
            update_result = await airtable_client.update_record(record_id, updated_fields)
            if update_result:
                print("Record updated:", update_result)
    except Exception as e:
        await log("error", "Exception occurred in main", exception=str(e))

# Run the example
asyncio.run(main()) 
