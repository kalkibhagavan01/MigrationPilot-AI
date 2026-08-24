from fastapi import APIRouter, Header, Response
from sqlalchemy.orm import Session
from fastapi import Depends

from app.db.session import get_db
from app.schemas.target import MockTargetEmployeeRequest, MockTargetEmployeeResponse
from app.services.mock_target import MockTargetService

router = APIRouter(prefix="/mock-target/v1", tags=["mock-target"])


@router.post("/employees", response_model=MockTargetEmployeeResponse)
def create_employee(
    payload: MockTargetEmployeeRequest,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    db: Session = Depends(get_db),
) -> MockTargetEmployeeResponse:
    result = MockTargetService(db).create_employee(idempotency_key, payload.model_dump())
    db.commit()
    response.status_code = result.http_status
    if result.target_record_id is None:
        return MockTargetEmployeeResponse(target_record_id="", status=result.error_code or "FAILED")
    return MockTargetEmployeeResponse(target_record_id=result.target_record_id, status="CREATED")


@router.delete("/employees/{target_record_id}", status_code=204)
def delete_employee(target_record_id: str, response: Response, db: Session = Depends(get_db)) -> None:
    result = MockTargetService(db).delete_employee(target_record_id)
    db.commit()
    response.status_code = 204 if result.http_status == 404 else result.http_status
