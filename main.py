from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, model_validator
from functions import log, AirtableClient  # Import AirtableClient
import traceback

# Define a Pydantic model for request validation
class RequestData(BaseModel):
    ghl_contact_id: str
    thread_id: str = None
    opportunity_stage: str
    opportunity_sub_stage: str = None  # Optional field
    airtable_record_id: str = None  # New optional field

    @model_validator(mode='before')
    def check_required_fields(cls, values):
        airtable_record_id = values.get('airtable_record_id')
        ghl_contact_id = values.get('ghl_contact_id')
        thread_id = values.get('thread_id')
        opportunity_stage = values.get('opportunity_stage')

        if airtable_record_id:
            if not opportunity_stage:
                raise ValueError("opportunity_stage is required when airtable_record_id is provided")
        else:
            if not (ghl_contact_id and thread_id and opportunity_stage):
                raise ValueError("ghl_contact_id, thread_id, and opportunity_stage are required when airtable_record_id is not provided")
        
        return values

app = FastAPI()

# Initialize AirtableClient with your credentials
airtable_client = AirtableClient(api_key="patMP43xP8KHVfepX.af949fb753d690b61bb9ce7cede5c66f908cbfe0086e0cecf354bd7ccc7077ac", base_id="appqlPGp6IWfdyZMp", table_id="tblD1vQglA9gq73i7")

@app.post("/update-opportunity")
async def update_opportunity(data: RequestData):
    await log("info", "Request received", data=data.model_dump())
    try:
        # Map incoming fields to Airtable fields
        fields = {
            "Opportunity Stage": data.opportunity_stage
        }
        
        # Include Opportunity Sub-Stage if provided
        if data.opportunity_sub_stage:
            fields["Opportunity Sub-Stage"] = data.opportunity_sub_stage

        if data.airtable_record_id:
            # Update the existing record
            updated_record = await airtable_client.update_record(data.airtable_record_id, fields)
            if updated_record:
                await log("info", f"{data.ghl_contact_id} updated to {data.opportunity_stage}", data=data.model_dump())
                return {"message": "Opportunity updated successfully", "record_id": data.airtable_record_id}
            else:
                raise HTTPException(status_code=500, detail="Failed to update opportunity in Airtable")
        else:
            # Create a new record
            fields.update({
                "GHL Contact ID": data.ghl_contact_id,
                "Thread ID": data.thread_id
            })
            record_id = await airtable_client.create_record(fields)
            if record_id:
                await log("info", f"New record created for {data.ghl_contact_id} with stage '{data.opportunity_stage}'", data=data.model_dump())
                return {"message": "Opportunity created successfully", "record_id": record_id}
            else:
                raise HTTPException(status_code=500, detail="Failed to create opportunity in Airtable")
    except Exception as e:
        error_trace = traceback.format_exc()
        await log("error", "Exception occurred", exception=str(e), traceback=error_trace, data=data.model_dump())
        raise HTTPException(status_code=400, detail="Code error")
