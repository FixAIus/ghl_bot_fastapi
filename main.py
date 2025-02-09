from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, model_validator
from AirtableClient import log, AirtableClient  # Adjusted import for AirtableClient
from GoHighLevelAPI import GoHighLevelAPI  # Import GoHighLevelAPI
import traceback
import os

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

# Initialize AirtableClient with environment variables
airtable_client = AirtableClient(
    api_key=os.getenv('AIRTABLE_API_KEY'),
    base_id=os.getenv('AIRTABLE_BASE_ID'),
    table_id=os.getenv('AIRTABLE_TABLE_ID')
)

# Initialize GoHighLevelAPI with environment variables
go_high_level_api = GoHighLevelAPI(
    location_id=os.getenv('GHL_LOCATION_ID')
)

@app.post("/update-opportunity")
async def update_opportunity(request: Request):
    try:
        incoming = await request.json()
        data = incoming.get("customData", {})
        validated_data = RequestData(**data)
        await log("info", "Request received", data=validated_data.model_dump())

        # Map incoming fields to Airtable fields
        fields = {
            "Opportunity Stage": validated_data.opportunity_stage
        }
        
        # Include Opportunity Sub-Stage if provided
        if validated_data.opportunity_sub_stage:
            fields["Opportunity Sub-Stage"] = validated_data.opportunity_sub_stage

        if validated_data.airtable_record_id:
            # Update the existing record
            updated_record = await airtable_client.update_record(validated_data.airtable_record_id, fields)
            if updated_record:
                await log("info", f"{validated_data.ghl_contact_id} updated to {validated_data.opportunity_stage}", data=validated_data.model_dump())
                return {"message": "Opportunity updated successfully", "record_id": validated_data.airtable_record_id}
            else:
                raise HTTPException(status_code=500, detail="Failed to update opportunity in Airtable")
        else:
            # Create a new record
            fields.update({
                "GHL Contact ID": validated_data.ghl_contact_id,
                "Thread ID": validated_data.thread_id
            })
            record_id = await airtable_client.create_record(fields)
            if record_id:
                # Update the GHL contact with the Airtable record ID
                update_data = {
                    "customFields": [
                        {"key": "airtable_record_id", "field_value": record_id}
                    ]
                }
                ghl_update_response = await go_high_level_api.update_contact(validated_data.ghl_contact_id, update_data)
                if ghl_update_response:
                    await log("info", f"New record created for {validated_data.ghl_contact_id} with stage '{validated_data.opportunity_stage}' and GHL contact updated", data=validated_data.model_dump())
                    return {"message": "Opportunity created and GHL contact updated successfully", "record_id": record_id}
                else:
                    await log("error", f"CRITICAL ERROR failed to update airtable", data=validated_data.model_dump())
                    raise HTTPException(status_code=500, detail="Failed to update GHL contact with Airtable record ID")
            else:
                raise HTTPException(status_code=500, detail="Failed to create opportunity in Airtable")
    except RequestValidationError as exc:
        await log("error", "Validation error", errors=exc.errors(), body=data)
        return JSONResponse(
            status_code=422,
            content={"detail": exc.errors(), "body": data},
        )
    except Exception as e:
        error_trace = traceback.format_exc()
        await log("error", "Exception occurred", exception=str(e), traceback=error_trace, data=data)
        raise HTTPException(status_code=400, detail="Code error")
