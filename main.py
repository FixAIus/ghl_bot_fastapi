from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, model_validator
from AirtableClient import log, AirtableClient  # Adjusted import for AirtableClient
import traceback
import os

# First, let's create separate models for each endpoint
class CreateOpportunityRequest(BaseModel):
    ghl_contact_id: str
    thread_id: str
    opportunity_stage: str
    opportunity_sub_stage: str = None

class UpdateOpportunityRequest(BaseModel):
    ghl_contact_id: str
    opportunity_stage: str
    airtable_record_id: str
    opportunity_sub_stage: str = None
    tier_1: str = None  # Optional field for Tier 1 updates

    @model_validator(mode='after')
    def validate_tier_1(self):
        if self.tier_1 is not None:
            # Convert string 'true'/'false' (case insensitive) to boolean
            self.tier_1 = str(self.tier_1).lower() == 'true'
        return self

app = FastAPI()

# Initialize AirtableClient with environment variables
airtable_client = AirtableClient(
    api_key=os.getenv('AIRTABLE_API_KEY'),
    base_id=os.getenv('AIRTABLE_BASE_ID'),
    table_id=os.getenv('AIRTABLE_TABLE_ID')
)

@app.post("/create-opportunity")
async def create_opportunity(request: Request):
    try:
        incoming = await request.json()
        data = incoming.get("customData", {})
        
        # Log raw incoming data first
        await log("info", "Create request received", raw_data=data)
        
        # Validate data for creating a new opportunity
        validated_data = CreateOpportunityRequest(**data)

        # Map incoming fields to Airtable fields
        fields = {
            "Opportunity Stage": validated_data.opportunity_stage,
            "GHL Contact ID": validated_data.ghl_contact_id,
            "Thread ID": validated_data.thread_id
        }
        
        # Include Opportunity Sub-Stage if provided
        if validated_data.opportunity_sub_stage:
            fields["Opportunity Sub-Stage"] = validated_data.opportunity_sub_stage

        # Create a new record
        record_id = await airtable_client.create_record(fields)
        if not record_id:
            error_msg = "Failed to create opportunity in Airtable"
            await log("error", error_msg, 
                     ghl_contact_id=validated_data.ghl_contact_id,
                     fields_attempted=fields)
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": error_msg}
            )

        await log("info", f"New record created for {validated_data.ghl_contact_id} with stage '{validated_data.opportunity_stage}'", 
                 data=validated_data.model_dump())
        return JSONResponse(
            status_code=200,
            content={"success": True, "record_id": record_id}
        )

    except RequestValidationError as exc:
        await log("error", "Validation error", 
                 errors=exc.errors(), 
                 raw_data=incoming.get("customData", {}) if 'incoming' in locals() else {})
        return JSONResponse(
            status_code=422,
            content={"success": False, "error": "Invalid request data", "details": exc.errors()},
        )
    except Exception as e:
        error_trace = traceback.format_exc()
        await log("error", "Exception occurred", 
                 exception=str(e), 
                 traceback=error_trace, 
                 raw_data=incoming.get("customData", {}) if 'incoming' in locals() else {})
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": str(e)}
        )

@app.post("/update-opportunity")
async def update_opportunity(request: Request):
    try:
        incoming = await request.json()
        data = incoming.get("customData", {})
        # Log raw incoming data first
        await log("info", "Update request received", raw_data=data)
        
        # Validate data for updating an existing opportunity
        validated_data = UpdateOpportunityRequest(**data)

        # Map incoming fields to Airtable fields
        fields = {
            "Opportunity Stage": validated_data.opportunity_stage
        }
        
        # Include Opportunity Sub-Stage if provided
        if validated_data.opportunity_sub_stage:
            fields["Opportunity Sub-Stage"] = validated_data.opportunity_sub_stage

        # Include Tier 1 if provided
        if validated_data.tier_1 is not None:
            fields["Tier 1"] = validated_data.tier_1

        # Update the existing record
        updated_record = await airtable_client.update_record(validated_data.airtable_record_id, fields)
        if not updated_record:
            error_msg = "Failed to update opportunity in Airtable"
            await log("error", error_msg,
                     ghl_contact_id=validated_data.ghl_contact_id,
                     fields_attempted=fields)
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": error_msg}
            )

        await log("info", f"Record updated for {validated_data.ghl_contact_id}", 
                 updated_fields=fields)
        return JSONResponse(
            status_code=200,
            content={"success": True, "message": "Update successful"}
        )

    except RequestValidationError as exc:
        await log("error", "Validation error", 
                 errors=exc.errors(), 
                 raw_data=incoming.get("customData", {}) if 'incoming' in locals() else {})
        return JSONResponse(
            status_code=422,
            content={"success": False, "error": "Invalid request data", "details": exc.errors()},
        )
    except Exception as e:
        error_trace = traceback.format_exc()
        await log("error", "Exception occurred", 
                 exception=str(e), 
                 traceback=error_trace, 
                 raw_data=incoming.get("customData", {}) if 'incoming' in locals() else {})
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": str(e)}
        )
